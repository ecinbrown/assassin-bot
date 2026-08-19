"""
PRDT Finance Webhook Trade Dispatcher Module
============================================
Dispatches validated Assassin strategy signals to PRDT Finance trade executors
via secure HTTP Webhooks or WebSocket callbacks.
"""
import asyncio
import json
import logging
import os
import time
from typing import Dict, Optional
import aiohttp

from .signal_engine import AssassinSignal

logger = logging.getLogger(__name__)


class PRDTWebhookDispatcher:
    def __init__(
        self,
        webhook_url: Optional[str] = None,
        api_key: Optional[str] = None,
        default_stake_usd: float = 10.0,
        simulation_mode: bool = False
    ):
        self.webhook_url = webhook_url or os.environ.get("PRDT_WEBHOOK_URL", "")
        self.api_key = api_key or os.environ.get("PRDT_API_KEY", "")
        self.default_stake = float(os.environ.get("PRDT_STAKE_USD", default_stake_usd))
        self.simulation_mode = simulation_mode or (not self.webhook_url)
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    def format_payload(self, signal: AssassinSignal, stake: Optional[float] = None) -> Dict:
        """Format the Assassin signal into PRDT standard execution payload."""
        amount = stake if stake is not None else self.default_stake
        # Normalize symbol for PRDT (e.g. BTCUSDT -> BTC/USD or BTC)
        asset_base = signal.symbol.replace("USDT", "").replace("USD", "")
        
        return {
            "source": "ASSASSIN_BOT",
            "asset": asset_base,
            "symbol": signal.symbol,
            "direction": "UP" if signal.action.lower() == 'call' else "DOWN",
            "action": signal.action.upper(),
            "entry_price": signal.price,
            "confidence": round(signal.confidence, 4),
            "amount_usd": amount,
            "duration_seconds": signal.expiry_seconds,
            "trigger": signal.trigger,
            "pattern": signal.pattern_type,
            "timestamp": int(signal.timestamp),
            "created_at": int(time.time())
        }

    async def dispatch_trade(self, signal: AssassinSignal, stake: Optional[float] = None) -> bool:
        """
        Send trade signal to PRDT Finance executor webhook.
        """
        payload = self.format_payload(signal, stake)
        
        logger.critical(
            f"🎯 [PRDT DISPATCH] {signal.symbol} | {signal.action.upper()} | "
            f"Price: ${signal.price:.2f} | Stake: ${payload['amount_usd']:.2f} | "
            f"Trigger: {signal.trigger}"
        )

        if self.simulation_mode:
            logger.info(f"🧪 [SIMULATION] Webhook payload generated: {json.dumps(payload)}")
            return True

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AssassinBot/1.0",
        }
        if self.api_key:
            headers["X-API-KEY"] = self.api_key
            headers["Authorization"] = f"Bearer {self.api_key}"

        session = await self._get_session()
        for attempt in range(1, 4):
            try:
                async with session.post(
                    self.webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=8)
                ) as resp:
                    resp_text = await resp.text()
                    if resp.status in (200, 201, 202):
                        logger.info(f"✅ PRDT Webhook Success (HTTP {resp.status}): {resp_text[:100]}")
                        return True
                    else:
                        logger.error(f"❌ PRDT Webhook Error (HTTP {resp.status}): {resp_text[:200]}")
            except Exception as e:
                logger.warning(f"PRDT Dispatch attempt #{attempt} failed: {e}")
                await asyncio.sleep(1)

        return False

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
