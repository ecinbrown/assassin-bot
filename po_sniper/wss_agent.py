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

# PocketOption WebSocket endpoints — demo uses demo-api prefix
PO_WSS_URLS = [
    "wss://demo-api-eu.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://demo-api-in.pocketoption.com/socket.io/?EIO=4&transport=websocket",
    "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket",
    "wss://api-in.pocketoption.com/socket.io/?EIO=4&transport=websocket",
]


class WSSAgent:
    """
    Pure WebSocket agent — no browser, no Chromium, no captcha.
    """

    def __init__(self, tick_queue: asyncio.Queue, headless: bool = True):
        self.tick_queue = tick_queue
        self.headless = headless
        self.is_running = False
        self.ws = None
        self._session = None

        self.pages = {}
        self.last_known_payout = 92
        self.base_stake = 10.0
        self.primary_page = None
        self.active_symbol = None
        self.MAX_PAIRS = 8

        # Auth — the SSID is the full 42["auth",...] message from browser DevTools
        # PO_SSID = full auth string, OR just the session token
        self.ssid = os.environ.get("PO_SSID", "")
        self.session_token = os.environ.get("PO_SESSION_TOKEN", "")
        self.uid = os.environ.get("PO_UID", "")
        self.demo_balance = 0.0

        self._asset_payouts = {}
        self._asset_catalog = {}
        self._subscribed_assets = set()

        self._authenticated = False
        self._reconnect_delay = 5
        self._url_idx = 0
        self._connect_attempts = 0

    async def start(self):
        self.is_running = True
        if not self.ssid and not self.session_token:
            logger.error(
                "❌ No auth credentials set!\n"
                "   Option A: Set PO_SSID = the full 42[\"auth\",...] message from browser DevTools\n"
                "   Option B: Set PO_SESSION_TOKEN + PO_UID\n"
                "   Option C: Send /token in Telegram"
            )
            while self.is_running and not self.ssid and not self.session_token:
                await asyncio.sleep(5)

        logger.info(f"🔌 WSS Agent starting...")
        await self._connect_loop()

    def update_token(self, new_token: str, new_uid: str = None):
        """Hot-update from Telegram /token command."""
        new_token = new_token.strip()
        # Check if user pasted full 42["auth",...] string
        if new_token.startswith('42["auth"') or new_token.startswith("42['auth'"):
            self.ssid = new_token
            self.session_token = ""
            logger.info("🔑 Full SSID auth string received!")
        else:
            self.session_token = new_token
            self.ssid = ""
        if new_uid:
            self.uid = new_uid.strip()
        self._authenticated = False
        self._reconnect_delay = 2
        self._url_idx = 0
        if self.ws and not self.ws.closed:
            asyncio.create_task(self.ws.close())

    async def stop(self):
        self.is_running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("🛑 WSS Agent stopped.")

    # ─── Connection ───────────────────────────────────────

    async def _connect_loop(self):
        while self.is_running:
            url = PO_WSS_URLS[self._url_idx % len(PO_WSS_URLS)]
            try:
                if self._session and not self._session.closed:
                    await self._session.close()

                self._session = aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=30)
                )
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
                    ssl=False,
                )
                logger.info("✅ WebSocket TCP connected!")

                # EIO=4 Step 1: Server sends '0{...}' open packet
                open_pkt = await self._recv_text(timeout=15)
                if not open_pkt or not open_pkt.startswith("0"):
                    raise ConnectionError(f"Bad handshake: {open_pkt[:80] if open_pkt else 'None'}")

                try:
                    eio_config = json.loads(open_pkt[1:])
                    logger.info(f"EIO open: sid={eio_config.get('sid','?')}")
                except json.JSONDecodeError:
                    pass

                # Step 2: Join namespace
                await self.ws.send_str("40")
                ns_pkt = await self._recv_text(timeout=10)
                if not ns_pkt or not ns_pkt.startswith("40"):
                    raise ConnectionError(f"Namespace fail: {ns_pkt[:80] if ns_pkt else 'None'}")
                logger.info("Socket.IO namespace joined!")

                # Step 3: Authenticate
                await self._send_auth()

                self._reconnect_delay = 5
                await self._message_loop()

            except asyncio.TimeoutError:
                logger.error(f"⏱️ Timeout on {url}")
            except Exception as e:
                logger.error(f"❌ Error: {type(e).__name__}: {e}")

            self._authenticated = False
            if self._session and not self._session.closed:
                await self._session.close()
            self._session = None
            self.ws = None

            if self.is_running:
                self._url_idx += 1
                wait = min(self._reconnect_delay, 60)
                logger.info(f"🔄 Reconnect in {wait}s (URL idx: {self._url_idx % len(PO_WSS_URLS)})...")
                await asyncio.sleep(wait)
                self._reconnect_delay = min(self._reconnect_delay * 1.5, 60)

    async def _send_auth(self):
        """Send auth — supports full SSID string OR sessionToken+uid."""
        if self.ssid:
            # Full 42["auth",...] string from browser — send as-is
            auth_str = self.ssid
            if not auth_str.startswith("42"):
                auth_str = f"42{auth_str}"
            await self.ws.send_str(auth_str)
            logger.info("📤 Auth sent (full SSID)")
        elif self.session_token:
            # Build auth from session token + uid
            # Try BOTH key formats — PO uses "session" in some versions, "sessionToken" in others
            auth1 = json.dumps([
                "auth",
                {
                    "session": self.session_token,
                    "isDemo": 1,
                    "uid": self.uid,
                    "lang": "en",
                    "platform": 2
                }
            ])
            await self.ws.send_str(f"42{auth1}")
            logger.info("📤 Auth sent (session key)")

            # Also try sessionToken key
            auth2 = json.dumps([
                "auth",
                {
                    "sessionToken": self.session_token,
                    "uid": self.uid,
                    "lang": "en",
                    "currentUrl": "cabinet/demo-quick-high-low",
                    "isChart": 1
                }
            ])
            await self.ws.send_str(f"42{auth2}")
            logger.info("📤 Auth sent (sessionToken key)")

    async def _recv_text(self, timeout=10):
        """Receive next TEXT message with actual timeout."""
        try:
            msg = await asyncio.wait_for(self.ws.receive(), timeout=timeout)
            if msg.type == aiohttp.WSMsgType.TEXT:
                return msg.data
            return None
        except asyncio.TimeoutError:
            logger.warning(f"recv_text timed out ({timeout}s)")
            return None
        except Exception as e:
            logger.warning(f"recv_text error: {e}")
            return None

    # ─── Message Loop ─────────────────────────────────────

    async def _message_loop(self):
        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.data

                    # EIO=4: Server ping '2' → respond pong '3'
                    if data == "2":
                        await self.ws.send_str("3")
                        continue
                    if data == "3":
                        continue

                    if data.startswith("42"):
                        try:
                            payload = json.loads(data[2:])
                            event = payload[0] if len(payload) > 0 else ""
                            edata = payload[1] if len(payload) > 1 else {}
                            await self._handle_event(event, edata)
                        except (json.JSONDecodeError, IndexError, KeyError):
                            logger.debug(f"Parse fail: {data[:80]}")

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning(f"WS closed: {msg.type}")
                    break
        except Exception as e:
            logger.error(f"Message loop: {e}")

    # ─── Events ───────────────────────────────────────────

    async def _handle_event(self, event: str, data):
        if event == "successauth":
            self._authenticated = True
            self.demo_balance = float(data.get("demoBalance", data.get("balance", 0)))
            logger.info(f"🔐 AUTH SUCCESS! Balance: ${self.demo_balance:.2f}")
            await self._request_market_data()

        elif event in ("failauth", "unauthorized", "error"):
            logger.error(f"❌ AUTH FAILED: {data}")
            self._authenticated = False

        elif event == "assets":
            if isinstance(data, dict):
                for k, v in data.items():
                    try: self._asset_catalog[int(k)] = v
                    except: pass
                logger.info(f"📦 {len(data)} assets loaded")
            elif isinstance(data, list):
                for a in data:
                    aid = a.get("id", a.get("asset_id"))
                    if aid: self._asset_catalog[int(aid)] = a
                logger.info(f"📦 {len(data)} assets loaded")

        elif event == "payout":
            if isinstance(data, dict):
                for k, v in data.items():
                    try: self._asset_payouts[int(k)] = int(v)
                    except: pass
                good = sum(1 for v in self._asset_payouts.values() if v >= 92)
                logger.info(f"📊 Payouts: {len(data)} total, {good} with >=92%")

        elif event in ("updateStream", "updateHistoryNew"):
            await self._process_tick(data)

        elif event == "candles":
            if isinstance(data, list):
                for c in data[-5:]:
                    await self._process_tick(c)

        elif event == "updateBalance":
            new = float(data.get("demoBalance", data.get("balance", self.demo_balance)))
            if new != self.demo_balance:
                logger.info(f"💰 Balance: ${self.demo_balance:.2f} → ${new:.2f}")
                self.demo_balance = new

        elif event == "successopenOrder":
            logger.info(f"📋 Order OPENED: id={data.get('id','?')}")

        elif event == "successcloseOrder":
            logger.info(f"📋 Order CLOSED: profit={data.get('profit', 0)}")

        elif event not in ("timeSync", "signal", "notification", "loadHistoryPeriod"):
            logger.info(f"[WSS] {event}: {str(data)[:120]}")

    async def _process_tick(self, data):
        if not isinstance(data, dict):
            return
        symbol_raw = data.get("symbol", data.get("asset", ""))
        price = data.get("price", data.get("close", data.get("value", 0)))
        ts = data.get("time", data.get("timestamp", time.time()))
        if not price or float(price) <= 0:
            return
        symbol = self._normalize_symbol(symbol_raw)
        if self.pages and symbol not in self.pages:
            return
        await self.tick_queue.put({
            "symbol": symbol, "price": float(price), "timestamp": float(ts),
        })

    async def _request_market_data(self):
        if not self.ws or self.ws.closed:
            return
        try:
            await self.ws.send_str('42["assets"]')
            await self.ws.send_str('42["payouts"]')
            logger.info("📡 Requested assets & payouts")
        except Exception as e:
            logger.error(f"Market data request failed: {e}")

    def _normalize_symbol(self, raw):
        if isinstance(raw, (int, float)):
            raw_int = int(raw)
            if raw_int in self._asset_catalog:
                info = self._asset_catalog[raw_int]
                return self._clean_name(info.get("name", info.get("symbol", f"asset_{raw_int}")))
            for sym, info in self.pages.items():
                if info.get("asset_id") == raw_int:
                    return sym
            return f"asset_{raw_int}"
        return self._clean_name(str(raw))

    def _clean_name(self, s):
        s = s.replace("/", "").replace(" ", "_")
        if "OTC" in s: s = s.replace("OTC", "otc")
        if "otc" in s.lower() and not s.endswith("_otc") and "_otc" not in s:
            s = s.rstrip("_") + "_otc"
        return s

    # ─── Asset Selection ──────────────────────────────────

    async def select_top_assets(self, max_assets=None, logic_engine=None):
        if max_assets is None:
            max_assets = self.MAX_PAIRS
        logger.info(f"🔍 Selecting top {max_assets} assets >=92% payout...")
        await self._request_market_data()
        await asyncio.sleep(5)

        candidates = []
        for aid, payout in self._asset_payouts.items():
            if payout >= 92:
                candidates.append((self._get_asset_name(aid), payout, aid))

        if not candidates:
            logger.warning("No payout data yet. Using bootstrap IDs 1-8.")
            for aid in range(1, max_assets + 1):
                candidates.append((self._get_asset_name(aid), 92, aid))

        candidates.sort(key=lambda x: x[1], reverse=True)
        selected = candidates[:max_assets]

        self.pages = {}
        for sym, payout, aid in selected:
            self.pages[sym] = {"payout": payout, "asset_id": aid}
            self._subscribed_assets.add(aid)
            if self.ws and not self.ws.closed:
                try: await self.ws.send_str(f'42{json.dumps(["subscribeSymbol", {"asset": aid}])}')
                except: pass

        if selected:
            self.active_symbol = selected[0][0]
            self.last_known_payout = selected[0][1]

        logger.info(f"🎯 {len(selected)} pairs: {[f'{s[0]}({s[1]}%)' for s in selected]}")
        return list(self.pages.keys())

    def _get_asset_name(self, aid):
        if aid in self._asset_catalog:
            return self._clean_name(self._asset_catalog[aid].get("name", f"asset_{aid}"))
        return f"asset_{aid}"

    # ─── Heartbeat & Watchdog ─────────────────────────────

    async def poll_ticks(self):
        while self.is_running:
            await asyncio.sleep(60)
            s = "✅" if self._authenticated else "❌"
            logger.info(f"💓 {s} Pairs:{len(self.pages)} Bal:${self.demo_balance:.2f} Payouts:{len(self._asset_payouts)}")

    async def payout_watchdog(self, logic_engine):
        while self.is_running:
            await asyncio.sleep(30)
            if not self._authenticated:
                continue
            try:
                current_ids = {info["asset_id"] for info in self.pages.values()}
                for symbol in list(self.pages.keys()):
                    info = self.pages[symbol]
                    aid = info.get("asset_id", 0)
                    payout = self._asset_payouts.get(aid, info.get("payout", 92))
                    if payout < 92:
                        logger.warning(f"⚠️ {symbol} → {payout}%!")
                        best_n, best_p, best_id = None, 0, None
                        for a, p in self._asset_payouts.items():
                            if a not in current_ids and p >= 92 and p > best_p:
                                best_p, best_id = p, a
                                best_n = self._get_asset_name(a)
                        if best_n and best_id:
                            del self.pages[symbol]
                            current_ids.discard(aid)
                            self.pages[best_n] = {"payout": best_p, "asset_id": best_id}
                            current_ids.add(best_id)
                            if self.ws and not self.ws.closed:
                                await self.ws.send_str(f'42{json.dumps(["subscribeSymbol", {"asset": best_id}])}')
                            if hasattr(logic_engine, 'target_symbols'):
                                if symbol in logic_engine.target_symbols:
                                    logic_engine.target_symbols.remove(symbol)
                                if best_n not in logic_engine.target_symbols:
                                    logic_engine.target_symbols.append(best_n)
                            logger.info(f"🔄 {symbol} → {best_n} ({best_p}%)")
                        else:
                            if not hasattr(logic_engine, 'blocked_symbols'):
                                logic_engine.blocked_symbols = set()
                            logic_engine.blocked_symbols.add(symbol)
                    else:
                        info["payout"] = payout
                        self.last_known_payout = payout
                        if hasattr(logic_engine, 'blocked_symbols') and symbol in logic_engine.blocked_symbols:
                            logic_engine.blocked_symbols.remove(symbol)
            except Exception as e:
                logger.error(f"Watchdog error: {e}")

    # ─── Trade Execution ──────────────────────────────────

    async def execute_trade(self, action: str, amount: float, symbol: str = None):
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

        order = json.dumps(["openOrder", {
            "asset": asset_id, "amount": stake, "action": action.lower(),
            "isDemo": 1, "requestId": int(time.time()*1000) + random.randint(100,999),
            "optionType": 100, "time": 60
        }])
        await self.ws.send_str(f"42{order}")
        logger.info(f"✅ TRADE: {action.upper()} ${stake:.2f} (34% of ${balance:.2f}) on {symbol}")
        return stake

    async def recover_browser(self):
        if self.ws and not self.ws.closed:
            await self.ws.close()
