"""
Binance Live Feed Module (Multi-TF WebSocket + REST Preloader + Auto-Failover)
===============================================================================
Streams real-time market data klines from Binance across MULTIPLE intervals
(1m, 3m, 5m) in a single combined WebSocket connection with:
1. Instant historical candle preloading via REST API on startup.
2. Multi-host WebSocket auto-failover.
3. Robust reconnection and heartbeats.
"""
import asyncio
import json
import logging
import time
from typing import List, Callable, Dict, Optional
import aiohttp

from .candle_utils import Candle

logger = logging.getLogger(__name__)

WS_HOSTS = [
    "wss://stream.binance.com:9443/stream?streams=",
    "wss://data-stream.binance.com:9443/stream?streams=",
    "wss://fstream.binance.com/stream?streams=",
    "wss://stream.binance.vision:9443/stream?streams=",
    "wss://stream.binance.us:9443/stream?streams=",
    "wss://stream.binance.com:443/stream?streams=",
]

REST_HOSTS = [
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
    "https://api.binance.us/api/v3/klines",
    "https://fapi.binance.com/fapi/v1/klines",
]


class BinanceFeed:
    """Multi-timeframe Binance WebSocket feed.
    
    Subscribes to all (symbol × interval) combinations in a single connection.
    Callback signature: on_candle_closed(symbol: str, interval: str, candle: Candle)
    """

    def __init__(
        self,
        symbols: List[str],
        intervals: List[str] = None,
        on_candle_closed: Optional[Callable] = None,
        # Legacy single-interval support
        interval: str = "1m",
    ):
        self.symbols = [s.lower() for s in symbols]
        # Support both new multi-interval and legacy single-interval API
        if intervals:
            self.intervals = intervals
        else:
            self.intervals = [interval]
        self.on_candle_closed = on_candle_closed
        self.is_running = False
        self.last_message_time: float = 0.0
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._current_host_idx = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            import socket
            resolver = aiohttp.ThreadedResolver()
            connector = aiohttp.TCPConnector(resolver=resolver, family=socket.AF_INET, ssl=False)
            self._session = aiohttp.ClientSession(connector=connector)
        return self._session

    def _build_stream_url(self, host_base: str) -> str:
        """Build combined stream URL for all symbols × intervals."""
        streams = []
        for s in self.symbols:
            for iv in self.intervals:
                streams.append(f"{s}@kline_{iv}")
        return f"{host_base}{'/'.join(streams)}"

    async def preload_history(self, limit: int = 50) -> Dict[str, Dict[str, List[Candle]]]:
        """
        Preload historical candles for ALL (symbol × interval) pairs.
        Returns: { "BTCUSDT": { "1m": [Candle, ...], "3m": [...], "5m": [...] }, ... }
        """
        session = await self._get_session()
        preloaded: Dict[str, Dict[str, List[Candle]]] = {}

        for sym in self.symbols:
            sym_upper = sym.upper()
            preloaded[sym_upper] = {}

            for iv in self.intervals:
                candles = []
                for host in REST_HOSTS:
                    url = f"{host}?symbol={sym_upper}&interval={iv}&limit={limit}"
                    try:
                        async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                for k in data:
                                    c = Candle(
                                        timestamp=float(k[0]) / 1000.0,
                                        open=float(k[1]),
                                        high=float(k[2]),
                                        low=float(k[3]),
                                        close=float(k[4]),
                                        volume=float(k[5]),
                                        trades=float(k[8]) if len(k) > 8 else 1.0
                                    )
                                    candles.append(c)
                                logger.info(f"✅ Preloaded {len(candles)} historical {iv} candles for {sym_upper}")
                                break
                    except Exception as e:
                        logger.debug(f"Preload from {host} failed for {sym_upper}/{iv}: {e}")

                preloaded[sym_upper][iv] = candles

        return preloaded

    async def start(self):
        """Start persistent WebSocket stream with automatic multi-host failover."""
        self.is_running = True
        total_streams = len(self.symbols) * len(self.intervals)
        logger.info(f"📡 Starting Binance Multi-TF Feed: {len(self.symbols)} pairs × {len(self.intervals)} TFs = {total_streams} streams")

        while self.is_running:
            host_base = WS_HOSTS[self._current_host_idx % len(WS_HOSTS)]
            stream_url = self._build_stream_url(host_base)
            logger.info(f"Connecting to: {host_base[:35]}...")

            try:
                session = await self._get_session()
                async with session.ws_connect(stream_url, heartbeat=25, timeout=aiohttp.ClientTimeout(connect=10)) as ws:
                    self._ws = ws
                    logger.info(f"🟢 Binance Multi-TF WebSocket connected! Streaming {total_streams} channels.")

                    async for msg in ws:
                        if not self.is_running:
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            self.last_message_time = time.time()
                            try:
                                payload = json.loads(msg.data)
                                await self._handle_kline_event(payload)
                            except Exception as e:
                                logger.error(f"Error parsing Binance kline: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"Binance WS connection closed: {msg.type}")
                            break

                # Loop exited cleanly (no exception) — still rotate + back off before reconnecting
                if self.is_running:
                    self._current_host_idx += 1
                    logger.info("Connection ended cleanly. Rotating to next endpoint after short delay...")
                    await asyncio.sleep(3)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Binance WS host failed ({e}). Rotating to next endpoint...")
                self._current_host_idx += 1
                await asyncio.sleep(3)

    async def _handle_kline_event(self, payload: Dict):
        """Process incoming Binance kline stream packet (multi-TF aware)."""
        data = payload.get('data', payload)
        if 'k' not in data:
            return

        k = data['k']
        is_closed = k.get('x', False)
        symbol = k.get('s', '').upper()
        interval = k.get('i', '1m')  # Binance includes the interval in the kline data

        if is_closed:
            candle = Candle(
                timestamp=float(k.get('t', time.time() * 1000)) / 1000.0,
                open=float(k.get('o')),
                high=float(k.get('h')),
                low=float(k.get('l')),
                close=float(k.get('c')),
                volume=float(k.get('v', 0.0)),
                trades=float(k.get('n', 1.0))
            )
            logger.info(
                f"📊 [{symbol}|{interval}] Candle Closed | O:{candle.open:.2f} H:{candle.high:.2f} "
                f"L:{candle.low:.2f} C:{candle.close:.2f} V:{candle.volume:.1f}"
            )

            if self.on_candle_closed:
                if asyncio.iscoroutinefunction(self.on_candle_closed):
                    await self.on_candle_closed(symbol, interval, candle)
                else:
                    self.on_candle_closed(symbol, interval, candle)

    async def stop(self):
        """Stop the WebSocket client."""
        self.is_running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
