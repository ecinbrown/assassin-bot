"""
Binance Live WebSocket Feed Module
==================================
Streams real-time market data klines (1m, 3m, 5m) from Binance Public WebSocket,
builds completed candles, and pushes them directly to the Assassin Strategy Engine.
"""
import asyncio
import json
import logging
import time
from typing import List, Callable, Dict, Optional
import aiohttp

from .candle_utils import Candle

logger = logging.getLogger(__name__)


class BinanceFeed:
    WS_BASE_URL = "wss://stream.binance.com:9443/ws"
    COMBINED_WS_URL = "wss://stream.binance.com:9443/stream?streams="

    def __init__(self, symbols: List[str], interval: str = "1m", on_candle_closed: Optional[Callable] = None):
        """
        Args:
            symbols: List of trading pairs, e.g. ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']
            interval: Kline timeframe, e.g. '1m', '3m', '5m'
            on_candle_closed: Async or sync callback fn(symbol, candle) invoked when a candle closes.
        """
        self.symbols = [s.lower() for s in symbols]
        self.interval = interval
        self.on_candle_closed = on_candle_closed
        self.is_running = False
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

    def _build_stream_url(self) -> str:
        streams = [f"{s}@kline_{self.interval}" for s in self.symbols]
        return f"{self.COMBINED_WS_URL}{'/'.join(streams)}"

    async def start(self):
        """Start the persistent Binance WebSocket stream."""
        self.is_running = True
        stream_url = self._build_stream_url()
        logger.info(f"Connecting to Binance Feed: {len(self.symbols)} streams on {self.interval}...")

        while self.is_running:
            try:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession()

                async with self._session.ws_connect(stream_url, heartbeat=30) as ws:
                    self._ws = ws
                    logger.info(" Binance WebSocket connected successfully!")

                    async for msg in ws:
                        if not self.is_running:
                            break

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                payload = json.loads(msg.data)
                                await self._handle_kline_event(payload)
                            except Exception as e:
                                logger.error(f"Error parsing Binance message: {e}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning(f"Binance WS closed: {msg.type}")
                            break

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Binance WS connection error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

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
                f"[{symbol}] Candle Closed | O:{candle.open:.2f} H:{candle.high:.2f} "
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
