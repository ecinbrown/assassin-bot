"""
Assassin Bot - Main Application Runner v2
==========================================
Full Price-Action Confluence Engine:
Binance Live Feeder → Assassin Confluence Engine → PRDT Finance Web3 Smart Contract
+ Interactive Telegram Controller & Live Alert Engine
"""
import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from typing import List, Optional

import aiohttp
from aiohttp import web

from assassin_strategy import (
    Candle,
    AssassinSignalEngine,
    AssassinSignal,
    BinanceFeed,
    PRDTAgent,
    PRDTWebhookDispatcher,
    AssassinTelegramBot
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AssassinBot")


class AssassinController:
    """Master controller managing runtime state, mode toggling, and services."""
    def __init__(
        self,
        symbols: List[str],
        interval: str = "1m",
        expiry_seconds: int = 300,
        stake_native: float = 0.01,
        simulation_mode: bool = True
    ):
        self.symbols = symbols
        self.interval = interval
        self.expiry_seconds = expiry_seconds
        self.stake_native = stake_native
        self.simulation_mode = simulation_mode
        self.paused = False
        
        self.engine: Optional[AssassinSignalEngine] = None
        self.prdt_agent: Optional[PRDTAgent] = None
        self.telegram_bot: Optional[AssassinTelegramBot] = None
        self.dispatcher: Optional[PRDTWebhookDispatcher] = None


async def main():
    logger.info("=" * 65)
    logger.info("  ASSASSIN BOT v2 — Real-Market Crypto Confluence Engine")
    logger.info("  ─────────────────────────────────────────────────────")
    logger.info("  Strategies: QM + OB + FVG + Doji + Engulfing + Exhaustion")
    logger.info("  Structure: S/R Zones + Round Numbers + Trendlines")
    logger.info("  Analysis: Regime Detection + 3-Tier Confluence Scoring")
    logger.info("  Execution: Web3 Smart Contract (PRDTAgent)")
    logger.info("  Feeder: Binance Live WebSocket (1m/3m/5m)")
    logger.info("  Telegram: Interactive Control + Real/Demo Mode Switcher")
    logger.info("=" * 65)

    # 1. Configuration from Environment
    symbols = os.environ.get("TRADING_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT").split(",")
    symbols = [s.strip() for s in symbols if s.strip()]
    interval = os.environ.get("CANDLE_INTERVAL", "1m")
    expiry_seconds = int(os.environ.get("TRADE_EXPIRY_SECONDS", "300"))

    # Web3 Smart Contract Configuration
    rpc_url = os.environ.get("PRDT_RPC_URL", "https://bsc-dataseed.binance.org/")
    contract_addr = os.environ.get("PRDT_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("WALLET_PRIVATE_KEY", "")
    stake_native = float(os.environ.get("PRDT_STAKE_NATIVE", "0.01"))
    simulation_mode = os.environ.get("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")

    # Telegram Credentials (supports ASSASSIN_TG_TOKEN & TELEGRAM_BOT_TOKEN)
    tg_token = os.environ.get("ASSASSIN_TG_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "")
    tg_chat_id = os.environ.get("ASSASSIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID", "")

    # Optional Webhook fallback URL
    webhook_url = os.environ.get("PRDT_WEBHOOK_URL", "")
    api_key = os.environ.get("PRDT_API_KEY", "")

    # 2. Instantiate Master Controller
    controller = AssassinController(
        symbols=symbols,
        interval=interval,
        expiry_seconds=expiry_seconds,
        stake_native=stake_native,
        simulation_mode=simulation_mode
    )

    # 3. Instantiate Engine & Web3 Agent
    engine = AssassinSignalEngine(
        doji_threshold=0.10,
        fvg_min_pct=0.01,
        swing_left=2,
        swing_right=2,
        safety_tolerance_pct=0.08,
        default_expiry_seconds=expiry_seconds,
        require_safety_retest=True,
    )
    controller.engine = engine

    prdt_agent = PRDTAgent(
        rpc_url=rpc_url,
        contract_address=contract_addr,
        private_key=private_key,
        default_stake_native=stake_native,
        min_buffer_seconds=20,
        simulation_mode=simulation_mode
    )
    prdt_agent.initialize()
    controller.prdt_agent = prdt_agent

    # Webhook Dispatcher (if configured)
    if webhook_url:
        controller.dispatcher = PRDTWebhookDispatcher(
            webhook_url=webhook_url,
            api_key=api_key,
            default_stake_usd=10.0,
            simulation_mode=simulation_mode
        )

    # 4. Instantiate Telegram Bot Controller
    tg_bot = None
    if tg_token:
        tg_bot = AssassinTelegramBot(
            token=tg_token,
            chat_id=tg_chat_id,
            main_controller=controller
        )
        if tg_bot.initialize():
            controller.telegram_bot = tg_bot

    # 5. Define Callback for Closed Candles
    async def on_candle_closed(symbol: str, candle: Candle):
        if controller.paused:
            return

        signals = engine.update_candle(symbol, candle)
        for sig in signals:
            verdict_icon = "🔥" if sig.verdict == "TAKE_IT" else "📊"
            logger.critical(
                f"{verdict_icon} SIGNAL: {sig.symbol} {sig.action.upper()} | "
                f"${sig.price:.2f} | {sig.verdict} ({sig.confidence*100:.0f}%) | "
                f"Solid={sig.solid_count} Soft={sig.soft_count} | "
                f"Regime={sig.regime} | {sig.trigger}"
            )

            # Send Telegram Alert
            if tg_bot:
                await tg_bot.send_signal_alert(sig)

            # 1. Execute via Web3 Smart Contract (PRDTAgent)
            success, tx_or_reason = await prdt_agent.execute_trade(sig, stake_native=controller.stake_native)
            if success:
                logger.info(f"✅ Trade Executed on PRDT Contract: {tx_or_reason}")
            else:
                logger.warning(f"⚠️ Trade Execution Failed / Skipped: {tx_or_reason}")

            # Send Trade Execution Alert to Telegram
            if tg_bot:
                await tg_bot.send_trade_alert(sig, tx_or_reason, success)

            # 2. Also dispatch to Webhook if configured
            if controller.dispatcher:
                await controller.dispatcher.dispatch_trade(sig)

    # 6. Background Auto-Claim Winnings Task (every 60s)
    async def auto_claim_worker():
        while True:
            try:
                await asyncio.sleep(60)
                if not controller.paused and not controller.simulation_mode:
                    txs = await prdt_agent.auto_claim_winnings()
                    if txs and tg_bot:
                        await tg_bot.send_claim_alert(txs)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Auto-claim tick error: {e}")

    claim_task = asyncio.create_task(auto_claim_worker())

    # 7. Start Telegram Bot Polling (if enabled)
    tg_task = None
    if tg_bot:
        tg_task = asyncio.create_task(tg_bot.start())

    # 8. Start HTTP Health Server (Required for Render Web Service)
    port = int(os.environ.get("PORT", 8080))
    async def handle_health(request):
        return web.Response(text="OK - Assassin Bot v2 Running", status=200)

    http_app = web.Application()
    http_app.router.add_get("/", handle_health)
    http_app.router.add_get("/health", handle_health)
    runner = web.AppRunner(http_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"🌐 HTTP Health server listening on port {port}")

    # 9. Start Binance Feed
    feed = BinanceFeed(
        symbols=controller.symbols,
        interval=controller.interval,
        on_candle_closed=on_candle_closed
    )

    try:
        logger.info(f"Armed with symbols: {controller.symbols} on {controller.interval} candles.")
        logger.info(f"Initial Execution Mode: {'🧪 SIMULATION (Demo)' if controller.simulation_mode else '🟢 LIVE ON-CHAIN (Real)'}")
        if tg_bot:
            logger.info("📱 Telegram Controller: ACTIVE")
        await feed.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Assassin Bot...")
    finally:
        claim_task.cancel()
        await runner.cleanup()
        if tg_bot:
            await tg_bot.stop()
        if tg_task:
            tg_task.cancel()
        await feed.stop()
        if controller.dispatcher:
            await controller.dispatcher.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
