"""
WSS Agent — Pure WebSocket replacement for BrowserAgent.

Connects directly to PocketOption's Socket.IO (EIO=4) WebSocket.
Uses ~30MB RAM instead of ~800MB (no Chromium needed).
"""
import asyncio
import json
import time
import os
import random
import logging
import aiohttp

logger = logging.getLogger(__name__)

# Multiple PocketOption WebSocket endpoints (tried in order)
PO_WSS_URLS = [
    "wss://api-l.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://api-l.po.trade/socket.io/?EIO=4&transport=websocket",
    "wss://demo-api-l.po.market/socket.io/?EIO=4&transport=websocket",
]


class WSSAgent:
    """
    Pure WebSocket agent — no browser, no Chromium, no captcha.
    Connects directly to PocketOption's WebSocket API using a session token.
    """

    def __init__(self, tick_queue: asyncio.Queue, headless: bool = True):
        self.tick_queue = tick_queue
        self.headless = headless
        self.is_running = False
        self.ws = None
        self._session = None

        self.pages = {}          # symbol -> {"payout": int, "asset_id": int}
        self.last_known_payout = 92
        self.base_stake = 10.0
        self.primary_page = None
        self.active_symbol = None
        self.MAX_PAIRS = 8

        # Auth — from env vars
        self.session_token = os.environ.get("PO_SESSION_TOKEN", "")
        self.uid = os.environ.get("PO_UID", "")
        self.demo_balance = 0.0

        # Server data
        self._asset_payouts = {}    # asset_id (int) -> payout (int)
        self._asset_catalog = {}    # asset_id (int) -> {"name": ..., ...}
        self._subscribed_assets = set()

        # Connection
        self._authenticated = False
        self._reconnect_delay = 5
        self._url_idx = 0
        self._connect_attempts = 0

    # ─── Public Interface ─────────────────────────────────

    async def start(self):
        self.is_running = True
        if not self.session_token or not self.uid:
            logger.error(
                "❌ PO_SESSION_TOKEN or PO_UID not set!\n"
                "   Option 1: Set them in Render Environment Variables.\n"
                "   Option 2: Send /token <TOKEN> <UID> in Telegram."
            )
            # Don't return — keep running so /token command can fix it
            while self.is_running and (not self.session_token or not self.uid):
                await asyncio.sleep(5)

        logger.info(f"🔌 WSS Agent starting (uid={self.uid}, token={self.session_token[:8]}...)")
        await self._connect_loop()

    def update_token(self, new_token: str, new_uid: str = None):
        """Hot-update session token from Telegram /token command."""
        self.session_token = new_token.strip()
        if new_uid:
            self.uid = new_uid.strip()
        self._authenticated = False
        self._reconnect_delay = 2
        self._url_idx = 0
        logger.info(f"🔑 Token updated! Reconnecting...")
        if self.ws and not self.ws.closed:
            asyncio.create_task(self.ws.close())

    async def stop(self):
        self.is_running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("🛑 WSS Agent stopped.")

    # ─── Connection Loop ──────────────────────────────────

    async def _connect_loop(self):
        while self.is_running:
            url = PO_WSS_URLS[self._url_idx % len(PO_WSS_URLS)]
            try:
                if self._session and not self._session.closed:
                    await self._session.close()

                self._session = aiohttp.ClientSession()
                self._connect_attempts += 1
                logger.info(f"📡 Attempt #{self._connect_attempts}: {url}")

                self.ws = await self._session.ws_connect(
                    url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/148.0.0.0 Safari/537.36"
                        ),
                        "Origin": "https://pocketoption.com",
                    },
                    heartbeat=30,
                    timeout=aiohttp.ClientTimeout(total=20),
                )
                logger.info("✅ WebSocket TCP connected!")

                # ── EIO=4 Handshake ──
                # Step 1: Server sends open packet: 0{"sid":"...","pingInterval":...}
                open_pkt = await self._recv_text(timeout=15)
                if not open_pkt or not open_pkt.startswith("0"):
                    raise ConnectionError(f"Expected '0{{...}}' open packet, got: {open_pkt[:60] if open_pkt else 'None'}")

                try:
                    eio_config = json.loads(open_pkt[1:])
                    self._ping_interval = eio_config.get("pingInterval", 25000) / 1000
                    self._ping_timeout = eio_config.get("pingTimeout", 20000) / 1000
                    logger.info(f"EIO handshake OK: sid={eio_config.get('sid','?')}, pingInterval={self._ping_interval}s")
                except json.JSONDecodeError:
                    self._ping_interval = 25
                    self._ping_timeout = 20

                # Step 2: Send '40' to join default Socket.IO namespace
                await self.ws.send_str("40")

                # Step 3: Wait for '40' namespace connect acknowledgement
                ns_pkt = await self._recv_text(timeout=10)
                if not ns_pkt or not ns_pkt.startswith("40"):
                    raise ConnectionError(f"Expected '40' namespace ack, got: {ns_pkt[:60] if ns_pkt else 'None'}")
                logger.info("Socket.IO namespace connected!")

                # Step 4: Authenticate — EXACT format from user's browser capture
                auth_payload = json.dumps([
                    "auth",
                    {
                        "sessionToken": self.session_token,
                        "uid": self.uid,
                        "lang": "en",
                        "currentUrl": "cabinet/demo-quick-high-low",
                        "isChart": 1
                    }
                ])
                await self.ws.send_str(f"42{auth_payload}")
                logger.info(f"📤 Auth sent (sessionToken format)")

                self._reconnect_delay = 5
                self._url_idx = 0

                # Enter message loop (blocks until disconnect)
                await self._message_loop()

            except asyncio.TimeoutError:
                logger.error(f"⏱️ Connection timed out on {url}")
            except Exception as e:
                logger.error(f"❌ WebSocket error: {type(e).__name__}: {e}")

            # Cleanup
            self._authenticated = False
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None
            self.ws = None

            if self.is_running:
                self._url_idx += 1  # Try next URL
                wait = min(self._reconnect_delay, 60)
                logger.info(f"🔄 Reconnecting in {wait}s (next URL idx: {self._url_idx % len(PO_WSS_URLS)})...")
                await asyncio.sleep(wait)
                self._reconnect_delay = min(self._reconnect_delay * 1.5, 60)

    async def _recv_text(self, timeout=10):
        """Receive next TEXT WebSocket message with timeout."""
        try:
            end = time.time() + timeout
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    return msg.data
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    return None
                if time.time() > end:
                    return None
        except Exception:
            return None

    # ─── Message Loop ─────────────────────────────────────

    async def _message_loop(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.data

                    # EIO=4: Server sends ping '2', we respond pong '3'
                    if data == "2":
                        await self.ws.send_str("3")
                        continue
                    if data == "3":
                        continue

                    # Socket.IO event: 42["event", data]
                    if data.startswith("42"):
                        try:
                            payload = json.loads(data[2:])
                            event = payload[0] if len(payload) > 0 else ""
                            edata = payload[1] if len(payload) > 1 else {}
                            await self._handle_event(event, edata)
                        except (json.JSONDecodeError, IndexError, KeyError):
                            logger.debug(f"Unparseable: {data[:80]}")

                    # Log any other unexpected packet types
                    elif not data.startswith("4"):
                        logger.debug(f"EIO pkt: {data[:60]}")

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning(f"WebSocket closed: {msg.type}")
                    break
        except Exception as e:
            logger.error(f"Message loop error: {e}")

    # ─── Event Handler ────────────────────────────────────

    async def _handle_event(self, event: str, data):

        if event == "successauth":
            self._authenticated = True
            self.demo_balance = float(data.get("demoBalance", data.get("balance", 0)))
            logger.info(f"🔐 AUTH SUCCESS! Demo Balance: ${self.demo_balance:.2f}")
            # Request market data immediately after auth
            await self._request_market_data()

        elif event == "failauth" or event == "unauthorized":
            logger.error(f"❌ AUTH FAILED: {data}")
            logger.error("   Send /token <NEW_TOKEN> <UID> in Telegram to update.")
            self._authenticated = False

        elif event == "assets":
            if isinstance(data, dict):
                for aid_str, info in data.items():
                    try:
                        self._asset_catalog[int(aid_str)] = info
                    except (ValueError, TypeError):
                        pass
                logger.info(f"📦 Received {len(data)} assets from server")
            elif isinstance(data, list):
                for asset in data:
                    aid = asset.get("id", asset.get("asset_id"))
                    if aid is not None:
                        self._asset_catalog[int(aid)] = asset
                logger.info(f"📦 Received {len(data)} assets from server (list)")

        elif event == "payout":
            if isinstance(data, dict):
                count = 0
                for aid_str, payout_val in data.items():
                    try:
                        self._asset_payouts[int(aid_str)] = int(payout_val)
                        count += 1
                    except (ValueError, TypeError):
                        pass
                if count > 0:
                    # Log assets with >=92% payout
                    good = {k: v for k, v in self._asset_payouts.items() if v >= 92}
                    logger.info(f"📊 Payouts received: {count} total, {len(good)} with >=92%")

        elif event in ("updateStream", "updateHistoryNew"):
            await self._process_tick(data)

        elif event == "candles":
            if isinstance(data, list):
                for c in data[-5:]:
                    await self._process_tick(c)

        elif event == "updateBalance":
            new_bal = float(data.get("demoBalance", data.get("balance", self.demo_balance)))
            if new_bal != self.demo_balance:
                logger.info(f"💰 Balance: ${self.demo_balance:.2f} → ${new_bal:.2f}")
                self.demo_balance = new_bal

        elif event == "successopenOrder":
            logger.info(f"📋 Order OPENED: id={data.get('id','?')} amount=${data.get('amount','?')}")

        elif event == "successcloseOrder":
            profit = data.get("profit", 0)
            win = float(profit) > 0 if profit else False
            logger.info(f"📋 Order CLOSED: profit=${profit} {'✅' if win else '❌'}")

        elif event in ("timeSync", "signal", "notification", "loadHistoryPeriod"):
            pass  # Noisy, ignore

        else:
            logger.info(f"[WSS] {event}: {str(data)[:150]}")

    async def _process_tick(self, data):
        """Extract price from tick/candle data and push to queue."""
        if not isinstance(data, dict):
            return

        symbol_raw = data.get("symbol", data.get("asset", ""))
        price = data.get("price", data.get("close", data.get("value", 0)))
        ts = data.get("time", data.get("timestamp", time.time()))

        if not price or float(price) <= 0:
            return

        symbol = self._normalize_symbol(symbol_raw)
        # Accept ticks for subscribed symbols, or all if no subscriptions yet
        if self.pages and symbol not in self.pages:
            return

        await self.tick_queue.put({
            "symbol": symbol,
            "price": float(price),
            "timestamp": float(ts),
        })

    async def _request_market_data(self):
        """Request assets and payouts from server after auth."""
        if not self.ws or self.ws.closed:
            return
        try:
            await self.ws.send_str('42["assets"]')
            await self.ws.send_str('42["payouts"]')
            logger.info("📡 Requested assets & payouts from server")
        except Exception as e:
            logger.error(f"Failed to request market data: {e}")

    def _normalize_symbol(self, raw):
        """Normalize symbol names to a consistent internal format."""
        if isinstance(raw, (int, float)):
            raw_int = int(raw)
            if raw_int in self._asset_catalog:
                info = self._asset_catalog[raw_int]
                name = info.get("name", info.get("symbol", f"asset_{raw_int}"))
                return self._clean_name(name)
            # Check existing pages
            for sym, info in self.pages.items():
                if info.get("asset_id") == raw_int:
                    return sym
            return f"asset_{raw_int}"

        return self._clean_name(str(raw))

    def _clean_name(self, s):
        s = s.replace("/", "").replace(" ", "_")
        # Normalize OTC suffix
        if "OTC" in s:
            s = s.replace("OTC", "otc")
        if "otc" in s.lower() and not s.endswith("_otc"):
            s = s.rstrip("_") + "_otc" if "_otc" not in s else s
        return s

    # ─── Asset Selection ──────────────────────────────────

    async def select_top_assets(self, max_assets=None, logic_engine=None):
        """
        Subscribe to top OTC assets with >=92% payout.
        FULLY DYNAMIC — no hardcoded pair list. Whatever the server says is >=92% gets picked.
        """
        if max_assets is None:
            max_assets = self.MAX_PAIRS

        logger.info(f"🔍 Selecting top {max_assets} assets with >=92% payout...")

        # Request fresh data
        await self._request_market_data()
        await asyncio.sleep(5)

        # Build candidates from ALL payouts received
        candidates = []
        for asset_id, payout in self._asset_payouts.items():
            if payout >= 92:
                name = self._get_asset_name(asset_id)
                candidates.append((name, payout, asset_id))

        if candidates:
            logger.info(f"Found {len(candidates)} assets with >=92% payout")
        else:
            logger.warning("No payout data from server yet. Will retry after ticks arrive.")
            # Subscribe to a few common IDs to bootstrap tick data
            # These are just IDs (numbers), NOT hardcoded pair names
            # The server will tell us what they are
            bootstrap_ids = list(range(1, 9))  # asset IDs 1-8
            for aid in bootstrap_ids:
                name = self._get_asset_name(aid)
                candidates.append((name, 92, aid))

        # Sort by payout descending, take top N
        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[:max_assets]

        self.pages = {}
        for sym, payout, asset_id in selected:
            self.pages[sym] = {"payout": payout, "asset_id": asset_id}
            self._subscribed_assets.add(asset_id)

            # Subscribe to price stream for this asset
            if self.ws and not self.ws.closed:
                try:
                    await self.ws.send_str(f'42{json.dumps(["subscribeSymbol", {"asset": asset_id}])}')
                except Exception:
                    pass

        if selected:
            self.active_symbol = selected[0][0]
            self.last_known_payout = selected[0][1]

        pair_summary = [f"{s[0]}({s[1]}%)" for s in selected]
        logger.info(f"🎯 Subscribed to {len(selected)} pairs: {pair_summary}")
        return list(self.pages.keys())

    def _get_asset_name(self, asset_id):
        """Get human-readable name for an asset ID."""
        if asset_id in self._asset_catalog:
            info = self._asset_catalog[asset_id]
            name = info.get("name", info.get("symbol", f"asset_{asset_id}"))
            return self._clean_name(name)
        return f"asset_{asset_id}"

    # ─── Tick Heartbeat ───────────────────────────────────

    async def poll_ticks(self):
        """Heartbeat logger — ticks arrive via _handle_event automatically."""
        while self.is_running:
            await asyncio.sleep(60)
            status = "CONNECTED ✅" if self._authenticated else "DISCONNECTED ❌"
            logger.info(
                f"💓 {status} | Pairs: {len(self.pages)} | "
                f"Balance: ${self.demo_balance:.2f} | "
                f"Payouts tracked: {len(self._asset_payouts)}"
            )

    # ─── Payout Watchdog ──────────────────────────────────

    async def payout_watchdog(self, logic_engine):
        """Swap pairs that drop below 92% for better ones."""
        while self.is_running:
            await asyncio.sleep(30)
            if not self._authenticated:
                continue
            try:
                current_ids = {info["asset_id"] for info in self.pages.values()}

                for symbol in list(self.pages.keys()):
                    info = self.pages[symbol]
                    asset_id = info.get("asset_id", 0)
                    current_payout = self._asset_payouts.get(asset_id, info.get("payout", 92))

                    if current_payout < 92:
                        logger.warning(f"⚠️ {symbol} dropped to {current_payout}%!")

                        # Find best replacement from ALL server assets
                        best_name, best_payout, best_id = None, 0, None
                        for aid, payout in self._asset_payouts.items():
                            if aid not in current_ids and payout >= 92 and payout > best_payout:
                                best_payout = payout
                                best_id = aid
                                best_name = self._get_asset_name(aid)

                        if best_name and best_id:
                            del self.pages[symbol]
                            current_ids.discard(asset_id)
                            self.pages[best_name] = {"payout": best_payout, "asset_id": best_id}
                            current_ids.add(best_id)

                            if self.ws and not self.ws.closed:
                                await self.ws.send_str(
                                    f'42{json.dumps(["subscribeSymbol", {"asset": best_id}])}'
                                )

                            if hasattr(logic_engine, 'target_symbols'):
                                if symbol in logic_engine.target_symbols:
                                    logic_engine.target_symbols.remove(symbol)
                                if best_name not in logic_engine.target_symbols:
                                    logic_engine.target_symbols.append(best_name)

                            logger.info(f"🔄 Swapped {symbol} → {best_name} ({best_payout}%)")
                        else:
                            if not hasattr(logic_engine, 'blocked_symbols'):
                                logic_engine.blocked_symbols = set()
                            logic_engine.blocked_symbols.add(symbol)
                            logger.warning(f"🚫 No >=92% replacement for {symbol}. Blocked.")
                    else:
                        info["payout"] = current_payout
                        self.last_known_payout = current_payout
                        if hasattr(logic_engine, 'blocked_symbols') and symbol in logic_engine.blocked_symbols:
                            logic_engine.blocked_symbols.remove(symbol)
            except Exception as e:
                logger.error(f"Payout watchdog error: {e}")

    # ─── Trade Execution ──────────────────────────────────

    async def execute_trade(self, action: str, amount: float, symbol: str = None):
        """Execute trade via WebSocket. Stake = 34% of balance."""
        if not self.ws or self.ws.closed or not self._authenticated:
            logger.error("Cannot trade: not connected!")
            return 0.0

        asset_id = None
        if symbol and symbol in self.pages:
            asset_id = self.pages[symbol].get("asset_id")
        else:
            for _, info in self.pages.items():
                asset_id = info.get("asset_id")
                break

        if asset_id is None:
            logger.error(f"No asset_id for {symbol}")
            return 0.0

        balance = self.demo_balance if self.demo_balance > 0 else self.base_stake
        stake = round(balance * 0.34, 2)
        stake = max(stake, 1.0)
        stake = min(stake, balance)

        request_id = int(time.time() * 1000) + random.randint(100, 999)

        order = json.dumps([
            "openOrder",
            {
                "asset": asset_id,
                "amount": stake,
                "action": action.lower(),
                "isDemo": 1,
                "requestId": request_id,
                "optionType": 100,
                "time": 60
            }
        ])

        await self.ws.send_str(f"42{order}")
        logger.info(f"✅ TRADE: {action.upper()} ${stake:.2f} (34% of ${balance:.2f}) on {symbol}")
        return stake

    async def recover_browser(self):
        """Force reconnect."""
        logger.info("🔄 Forcing WebSocket reconnect...")
        if self.ws and not self.ws.closed:
            await self.ws.close()
