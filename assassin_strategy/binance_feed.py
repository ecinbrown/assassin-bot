"""
Binance Live Feed Module (WebSocket + REST Preloader + Auto-Failover)
====================================================================
Streams real-time market data klines (1m, 3m, 5m) from Binance with:
1. Instant historical candle preloading via REST API on startup (0-minute cold start).
2. Multi-host WebSocket auto-failover (stream.binance.com, data-stream, vision, fstream).
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
    "wss://stream.binance.vision:9443/stream?streams=",
    "wss://stream.binance.com:443/stream?streams=",
]

REST_HOSTS = [
    "https://api.binance.com/api/v3/klines",
    "https://api1.binance.com/api/v3/klines",
    "https://api2.binance.com/api/v3/klines",
    "https://api3.binance.com/api/v3/klines",
    "https://data-api.binance.vision/api/v3/klines",
]


class BinanceFeed:
    def __init__(self, symbols: List[str], interval: str = "1m", on_candle_closed: Optional[Callable] = None):
        self.symbols = [s.lower() for s in symbols]
        self.interval = interval
        self.on_candle_closed = on_candle_closed
        self.is_running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._current_host_idx = 0

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def _build_stream_url(self, host_base: str) -> str:
        streams = [f"{s}@kline_{self.interval}" for s in self.symbols]
        return f"{host_base}{'/'.join(streams)}"

    async def preload_history(self, limit: int = 50) -> Dict[str, List[Candle]]:
        """
        Preload historical candles via REST API on startup.
        Eliminates the 15-minute cold start delay.
        """
        session = await self._get_session()
        preloaded = {}

        for sym in self.symbols:
            sym_upper = sym.upper()
            candles = []
            for host in REST_HOSTS:
                url = f"{host}?symbol={sym_upper}&interval={self.interval}&limit={limit}"
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
                                    volume=float(k[5])
                                )
                                candles.append(c)
                            logger.info(f"✅ Preloaded {len(candles)} historical {self.interval} candles for {sym_upper}")
                            break
                except Exception as e:
                    logger.debug(f"Preload from {host} failed: {e}")

            preloaded[sym_upper] = candles

        return preloaded

    async def start(self):
        """Start persistent WebSocket stream with automatic multi-host failover."""
        self.is_running = True
        logger.info(f"📡 Starting Binance Live Feed for {len(self.symbols)} pairs on {self.interval}...")

        while self.is_running:
            host_base = WS_HOSTS[self._current_host_idx % len(WS_HOSTS)]
            stream_url = self._build_stream_url(host_base)
            logger.info(f"Connecting to: {host_base[:35]}...")

            try:
                session = await self._get_session()
                async with session.ws_connect(stream_url, heartbeat=25, timeout=aiohttp.ClientTimeout(total=10)) as ws:
                    self._ws = ws
                    logger.info("🟢 Binance Live WebSocket connected and streaming!")

                    async for msg in ws:
                        if not self.is_running:
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                                await self._handle_kline_event(payload)
                            except Exception as e:
                                logger.error(f"Error parsing Binance kline: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"Binance WS connection closed: {msg.type}")
                            break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Binance WS host failed ({e}). Rotating to next endpoint...")
                self._current_host_idx += 1
                await asyncio.sleep(3)

    async def _handle_kline_event(self, payload: Dict):
        """Process incoming Binance kline stream packet."""
        data = payload.get('data', payload)
        if 'k' not in data:
            return

        k = data['k']
        is_closed = k.get('x', False)  # 'x' is True when candle has finished/closed
        symbol = k.get('s', '').upper()

        if is_closed:
            candle = Candle(
                timestamp=float(k.get('t', time.time() * 1000)) / 1000.0,
                open=float(k.get('o')),
                high=float(k.get('h')),
                low=float(k.get('l')),
                close=float(k.get('c')),
                volume=float(k.get('v', 0.0))
            )
            logger.info(
                f"📊 [{symbol}] Candle Closed | O:{candle.open:.2f} H:{candle.high:.2f} "
                f"L:{candle.low:.2f} C:{candle.close:.2f} V:{candle.volume:.1f}"
            )

            if self.on_candle_closed:
                if asyncio.iscoroutinefunction(self.on_candle_closed):
                    await self.on_candle_closed(symbol, candle)
                else:
                    self.on_candle_closed(symbol, candle)

    async def stop(self):
        """Stop the WebSocket client."""
        self.is_running = False
        if self._ws and not self._ws.closed:
            await self._ws.close()
        if self._session and not self._session.closed:
            await self._session.close()
