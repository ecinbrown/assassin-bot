"""
WSS Agent — Pure WebSocket replacement for BrowserAgent.

Connects directly to PocketOption's Socket.IO WebSocket.
Uses ~30MB RAM instead of ~800MB (no Chromium needed).
Handles: auth, price streaming, asset selection, payout monitoring, trade execution.
"""
import asyncio
import json
import time
import os
import random
import logging
import aiohttp

logger = logging.getLogger(__name__)

# PocketOption WebSocket endpoint
PO_WSS_URL = "wss://api-l.po.market/socket.io/?EIO=4&transport=websocket"

# OTC asset IDs mapping (symbol_name -> asset_id)
# These are the standard OTC pairs available on PocketOption
OTC_ASSETS = {
    "EURUSD_otc": {"id": 1, "name": "EUR/USD OTC"},
    "EURGBP_otc": {"id": 2, "name": "EUR/GBP OTC"},
    "GBPJPY_otc": {"id": 3, "name": "GBP/JPY OTC"},
    "AUDUSD_otc": {"id": 4, "name": "AUD/USD OTC"},
    "GBPUSD_otc": {"id": 5, "name": "GBP/USD OTC"},
    "USDJPY_otc": {"id": 6, "name": "USD/JPY OTC"},
    "USDCHF_otc": {"id": 7, "name": "USD/CHF OTC"},
    "EURJPY_otc": {"id": 8, "name": "EUR/JPY OTC"},
    "NZDUSD_otc": {"id": 9, "name": "NZD/USD OTC"},
    "USDCAD_otc": {"id": 10, "name": "USD/CAD OTC"},
    "AUDCAD_otc": {"id": 14, "name": "AUD/CAD OTC"},
    "AUDCHF_otc": {"id": 15, "name": "AUD/CHF OTC"},
    "AUDJPY_otc": {"id": 16, "name": "AUD/JPY OTC"},
    "CADCHF_otc": {"id": 17, "name": "CAD/CHF OTC"},
    "CADJPY_otc": {"id": 18, "name": "CAD/JPY OTC"},
    "CHFJPY_otc": {"id": 19, "name": "CHF/JPY OTC"},
    "EURAUD_otc": {"id": 20, "name": "EUR/AUD OTC"},
    "EURCAD_otc": {"id": 21, "name": "EUR/CAD OTC"},
    "EURCHF_otc": {"id": 22, "name": "EUR/CHF OTC"},
    "EURNZD_otc": {"id": 23, "name": "EUR/NZD OTC"},
    "GBPAUD_otc": {"id": 24, "name": "GBP/AUD OTC"},
    "GBPCAD_otc": {"id": 25, "name": "GBP/CAD OTC"},
    "GBPCHF_otc": {"id": 26, "name": "GBP/CHF OTC"},
    "GBPNZD_otc": {"id": 27, "name": "GBP/NZD OTC"},
    "NZDCAD_otc": {"id": 28, "name": "NZD/CAD OTC"},
    "NZDCHF_otc": {"id": 29, "name": "NZD/CHF OTC"},
    "NZDJPY_otc": {"id": 30, "name": "NZD/JPY OTC"},
    "#AXP_otc":   {"id": 31, "name": "American Express OTC"},
    "#AAPL_otc":  {"id": 32, "name": "Apple OTC"},
    "#BA_otc":    {"id": 33, "name": "Boeing OTC"},
    "#CSCO_otc":  {"id": 34, "name": "Cisco OTC"},
    "#INTC_otc":  {"id": 35, "name": "Intel OTC"},
    "#MSFT_otc":  {"id": 36, "name": "Microsoft OTC"},
    "#TSLA_otc":  {"id": 37, "name": "Tesla OTC"},
    "Bitcoin_otc":  {"id": 40, "name": "Bitcoin OTC"},
    "Ethereum_otc": {"id": 41, "name": "Ethereum OTC"},
}


class WSSAgent:
    """
    Pure WebSocket agent — no browser, no Chromium, no captcha, no login page.
    Connects directly to PocketOption's WebSocket API using a session token.
    """

    def __init__(self, tick_queue: asyncio.Queue, headless: bool = True):
        self.tick_queue = tick_queue
        self.headless = headless
        self.is_running = False
        self.ws = None
        self._session = None

        # Mimic BrowserAgent interface
        self.pages = {}  # symbol -> {"payout": int}
        self.last_known_payout = 92
        self.base_stake = 10.0
        self.primary_page = None  # Not used, but keeps telegram bot happy
        self.active_symbol = None

        # Auth
        self.session_token = os.environ.get("PO_SESSION_TOKEN", "")
        self.uid = os.environ.get("PO_UID", "")
        self.demo_balance = 0.0

        # Asset payouts received from server
        self._asset_payouts = {}  # asset_id -> payout_percent
        self._subscribed_assets = set()

        # Connection state
        self._authenticated = False
        self._reconnect_delay = 5

    async def start(self):
        """Connect to PocketOption WebSocket and authenticate."""
        self.is_running = True

        if not self.session_token or not self.uid:
            logger.error(
                "❌ Missing PO_SESSION_TOKEN or PO_UID environment variables!\n"
                "   Set them in Render Environment:\n"
                "   PO_SESSION_TOKEN = your sessionToken from WebSocket auth message\n"
                "   PO_UID = your uid from WebSocket auth message"
            )
            return

        logger.info("🔌 Connecting to PocketOption WebSocket (NO BROWSER)...")
        await self._connect()

    async def _connect(self):
        """Establish WebSocket connection with auto-reconnect."""
        while self.is_running:
            try:
                self._session = aiohttp.ClientSession()
                self.ws = await self._session.ws_connect(
                    PO_WSS_URL,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Origin": "https://po.trade",
                    },
                    heartbeat=25,
                    timeout=aiohttp.ClientWSMsgType(total=30),
                )
                logger.info("✅ WebSocket connected!")

                # Socket.IO handshake: wait for '0{...}' open packet
                async for msg in self.ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if msg.data.startswith("0"):
                            logger.info(f"Socket.IO handshake received")
                            # Send '40' to connect to default namespace
                            await self.ws.send_str("40")
                            break

                # Wait for '40' acknowledgement
                async for msg in self.ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        if msg.data.startswith("40"):
                            logger.info("Socket.IO namespace connected!")
                            break

                # Send authentication
                auth_payload = json.dumps([
                    "auth",
                    {
                        "session": self.session_token,
                        "isDemo": 1,
                        "uid": self.uid,
                        "lang": "en",
                        "platform": 2
                    }
                ])
                await self.ws.send_str(f"42{auth_payload}")
                logger.info(f"📤 Auth sent for uid={self.uid}")

                self._authenticated = True
                self._reconnect_delay = 5
                
                # Start message processing loop
                await self._message_loop()

            except Exception as e:
                logger.error(f"WebSocket error: {e}")
                self._authenticated = False
                
            finally:
                if self._session and not self._session.closed:
                    await self._session.close()
                    self._session = None
                self.ws = None

            if self.is_running:
                logger.info(f"🔄 Reconnecting in {self._reconnect_delay}s...")
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(self._reconnect_delay * 2, 60)

    async def _message_loop(self):
        """Process incoming WebSocket messages."""
        ping_task = asyncio.create_task(self._keep_alive())

        try:
            async for msg in self.ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = msg.data

                    # Socket.IO ping/pong
                    if data == "2":
                        await self.ws.send_str("3")
                        continue
                    if data == "3":
                        continue

                    # Socket.IO event messages
                    if data.startswith("42"):
                        try:
                            payload = json.loads(data[2:])
                            event = payload[0]
                            event_data = payload[1] if len(payload) > 1 else {}
                            await self._handle_event(event, event_data)
                        except (json.JSONDecodeError, IndexError) as e:
                            pass

                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning(f"WebSocket closed/error: {msg.type}")
                    break
        finally:
            ping_task.cancel()

    async def _keep_alive(self):
        """Send Socket.IO pings every 25s."""
        while self.is_running:
            try:
                await asyncio.sleep(25)
                if self.ws and not self.ws.closed:
                    await self.ws.send_str("2")
            except Exception:
                break

    async def _handle_event(self, event: str, data):
        """Route incoming Socket.IO events."""

        if event == "successauth":
            logger.info(f"🔐 Authentication successful! isDemo={data.get('isDemo')}")
            self.demo_balance = data.get('demoBalance', 0)
            logger.info(f"💰 Demo Balance: ${self.demo_balance}")

        elif event == "updateStream":
            # Real-time tick data
            symbol_raw = data.get("symbol", data.get("asset", ""))
            price = data.get("price", data.get("close", data.get("value", 0)))
            ts = data.get("time", data.get("timestamp", time.time()))

            if price and price > 0:
                # Normalize the symbol name
                symbol = self._normalize_symbol(symbol_raw)
                if symbol in self.pages or not self.pages:
                    await self.tick_queue.put({
                        "symbol": symbol,
                        "price": float(price),
                        "timestamp": float(ts),
                    })

        elif event == "updateHistoryNew":
            # Candle/history update (same format browser intercepted)
            symbol_raw = data.get("symbol", data.get("asset", ""))
            price = data.get("price", data.get("close", data.get("value", 0)))
            ts = data.get("time", data.get("timestamp", time.time()))

            if price and price > 0:
                symbol = self._normalize_symbol(symbol_raw)
                if symbol in self.pages or not self.pages:
                    await self.tick_queue.put({
                        "symbol": symbol,
                        "price": float(price),
                        "timestamp": float(ts),
                    })

        elif event == "candles":
            # Batch candle data
            if isinstance(data, list):
                for candle in data[-5:]:  # Only process recent candles
                    price = candle.get("close", candle.get("price", 0))
                    ts = candle.get("time", time.time())
                    symbol = self._normalize_symbol(candle.get("symbol", candle.get("asset", "")))
                    if price and price > 0 and symbol in self.pages:
                        await self.tick_queue.put({
                            "symbol": symbol,
                            "price": float(price),
                            "timestamp": float(ts),
                        })

        elif event == "payout":
            # Payout updates for assets
            if isinstance(data, dict):
                for asset_id_str, payout in data.items():
                    try:
                        self._asset_payouts[int(asset_id_str)] = int(payout)
                    except (ValueError, TypeError):
                        pass

        elif event == "updateBalance":
            self.demo_balance = data.get("demoBalance", self.demo_balance)

        elif event == "successcloseOrder":
            logger.info(f"📋 Order closed: profit={data.get('profit', 0)}")

        elif event == "successopenOrder":
            logger.info(f"📋 Order opened successfully: id={data.get('id', '?')}")

        elif event in ("timeSync", "signal", "notification"):
            pass  # Ignore noisy events

        else:
            # Log unknown events for debugging (truncated)
            data_str = str(data)[:150]
            logger.debug(f"[WSS] {event}: {data_str}")

    def _normalize_symbol(self, raw):
        """Convert server symbol format to our internal format."""
        if isinstance(raw, (int, float)):
            # Reverse lookup from asset ID
            for sym, info in OTC_ASSETS.items():
                if info["id"] == int(raw):
                    return sym
            return f"asset_{raw}"
        
        s = str(raw)
        # Handle formats like "EURUSD_otc", "EUR/USD OTC", "#AAPL_otc", etc.
        s = s.replace("/", "").replace(" ", "_").replace("OTC", "otc")
        if not s.endswith("_otc") and "otc" in s.lower():
            s = s.replace("otc", "_otc")
        return s

    async def select_top_assets(self, max_assets=5, logic_engine=None):
        """
        Subscribe to top OTC assets with highest payouts.
        Pure WebSocket — no browser clicks needed.
        """
        logger.info(f"🔍 Scanning for top {max_assets} assets with >=92% payout (via WebSocket)...")

        # Request payout data from server
        if self.ws and not self.ws.closed:
            await self.ws.send_str('42["payouts"]')
            # Give server time to respond
            await asyncio.sleep(3)

        # Filter assets with >= 92% payout
        valid_assets = []
        for sym, info in OTC_ASSETS.items():
            asset_id = info["id"]
            payout = self._asset_payouts.get(asset_id, 0)
            if payout >= 92:
                valid_assets.append((sym, payout, asset_id))

        # If no payout data yet, subscribe to ALL OTC pairs and use defaults
        if not valid_assets:
            logger.warning("No payout data received yet. Subscribing to top OTC pairs with assumed 92% payout...")
            default_pairs = ["EURUSD_otc", "EURGBP_otc", "GBPJPY_otc", "AUDUSD_otc", "GBPUSD_otc"]
            for sym in default_pairs[:max_assets]:
                valid_assets.append((sym, 92, OTC_ASSETS[sym]["id"]))

        # Sort by payout descending, take top N
        valid_assets.sort(key=lambda x: x[1], reverse=True)
        selected = valid_assets[:max_assets]

        self.pages = {}
        for sym, payout, asset_id in selected:
            self.pages[sym] = {"payout": payout, "asset_id": asset_id}
            self._subscribed_assets.add(asset_id)
            logger.info(f"✅ Subscribed to {sym} (payout: {payout}%, id: {asset_id})")

            # Subscribe to this asset's stream
            if self.ws and not self.ws.closed:
                subscribe_msg = json.dumps(["subscribeSymbol", {"asset": asset_id}])
                await self.ws.send_str(f"42{subscribe_msg}")

        if selected:
            self.active_symbol = selected[0][0]
            self.last_known_payout = selected[0][1]

        return list(self.pages.keys())

    async def poll_ticks(self):
        """
        No-op for WSS mode — ticks arrive via _handle_event automatically.
        This method exists for interface compatibility with main.py.
        """
        while self.is_running:
            await asyncio.sleep(60)
            if self._authenticated:
                logger.info(
                    f"📡 WSS alive | Subscribed: {list(self.pages.keys())} | "
                    f"Balance: ${self.demo_balance:.2f}"
                )

    async def payout_watchdog(self, logic_engine):
        """Monitor payouts via WebSocket data and swap pairs if needed."""
        while self.is_running:
            await asyncio.sleep(30)
            try:
                for symbol in list(self.pages.keys()):
                    info = self.pages[symbol]
                    asset_id = info.get("asset_id", 0)
                    current_payout = self._asset_payouts.get(asset_id, info.get("payout", 92))
                    
                    if current_payout < 92:
                        logger.warning(f"⚠️ Payout for {symbol} dropped to {current_payout}%! Swapping...")
                        
                        # Find a replacement
                        best_replacement = None
                        best_payout = 0
                        for sym, sym_info in OTC_ASSETS.items():
                            if sym not in self.pages:
                                p = self._asset_payouts.get(sym_info["id"], 0)
                                if p >= 92 and p > best_payout:
                                    best_replacement = sym
                                    best_payout = p

                        if best_replacement:
                            new_info = OTC_ASSETS[best_replacement]
                            del self.pages[symbol]
                            self.pages[best_replacement] = {"payout": best_payout, "asset_id": new_info["id"]}
                            
                            # Subscribe to new asset
                            if self.ws and not self.ws.closed:
                                sub_msg = json.dumps(["subscribeSymbol", {"asset": new_info["id"]}])
                                await self.ws.send_str(f"42{sub_msg}")
                            
                            if hasattr(logic_engine, 'target_symbols'):
                                if symbol in logic_engine.target_symbols:
                                    logic_engine.target_symbols.remove(symbol)
                                if best_replacement not in logic_engine.target_symbols:
                                    logic_engine.target_symbols.append(best_replacement)

                            logger.info(f"🔄 Swapped {symbol} -> {best_replacement} (payout: {best_payout}%)")
                        else:
                            logger.warning(f"No replacement found for {symbol}. Blocking.")
                            if not hasattr(logic_engine, 'blocked_symbols'):
                                logic_engine.blocked_symbols = set()
                            logic_engine.blocked_symbols.add(symbol)
                    else:
                        # Update stored payout
                        info["payout"] = current_payout
                        self.last_known_payout = current_payout
                        if hasattr(logic_engine, 'blocked_symbols') and symbol in logic_engine.blocked_symbols:
                            logic_engine.blocked_symbols.remove(symbol)
                            logger.info(f"✅ Payout for {symbol} recovered to {current_payout}%. Resuming trades.")
            except Exception as e:
                logger.error(f"Payout watchdog error: {e}")

    async def execute_trade(self, action: str, amount: float, symbol: str = None):
        """Execute a trade via WebSocket — no browser button clicking."""
        if not self.ws or self.ws.closed or not self._authenticated:
            logger.error("Cannot trade: WebSocket not connected!")
            return 0.0

        # Find the asset ID
        asset_id = None
        if symbol and symbol in self.pages:
            asset_id = self.pages[symbol].get("asset_id")
        elif symbol and symbol in OTC_ASSETS:
            asset_id = OTC_ASSETS[symbol]["id"]
        else:
            # Use first subscribed asset
            for sym, info in self.pages.items():
                asset_id = info.get("asset_id")
                break

        if asset_id is None:
            logger.error(f"Cannot find asset_id for {symbol}")
            return 0.0

        stake = amount if amount > 0 else self.base_stake
        request_id = int(time.time() * 1000) + random.randint(100, 999)

        order_payload = json.dumps([
            "openOrder",
            {
                "asset": asset_id,
                "amount": stake,
                "action": action.lower(),
                "isDemo": 1,
                "requestId": request_id,
                "optionType": 100,
                "time": 60  # 60 second expiry (server will use the closest valid expiry)
            }
        ])

        await self.ws.send_str(f"42{order_payload}")
        logger.info(f"✅ WSS Trade: {action.upper()} ${stake:.2f} on {symbol} (asset_id={asset_id})")
        return stake

    async def recover_browser(self):
        """Reconnect WebSocket on failure."""
        logger.info("🔄 Reconnecting WebSocket...")
        if self.ws and not self.ws.closed:
            await self.ws.close()
        # _connect loop will handle reconnection

    async def stop(self):
        """Clean shutdown."""
        self.is_running = False
        if self.ws and not self.ws.closed:
            await self.ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("🛑 WSS Agent stopped.")
