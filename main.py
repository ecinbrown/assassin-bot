"""
Assassin Bot - Main Application Runner v2
==========================================
Full Price-Action Confluence Engine — Binance Live → Assassin Analysis → PRDT Finance
"""
import asyncio
import logging
import os
import sys

from assassin_strategy import (
    Candle,
    AssassinSignalEngine,
    AssassinSignal,
    BinanceFeed,
    PRDTWebhookDispatcher
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AssassinBot")


async def main():
    logger.info("=" * 65)
    logger.info("  ASSASSIN BOT v2 — Pure Price-Action Confluence Engine")
    logger.info("  ─────────────────────────────────────────────────────")
    logger.info("  Patterns: QM + OB + FVG + Doji + Engulfing + Exhaustion")
    logger.info("  Structure: S/R Zones + Round Numbers + Trendlines")
    logger.info("  Analysis: Regime Detection + Confluence Scoring")
    logger.info("  Verdict: Take It (3+ solid) | Lean (2+1) | Leave It")
    logger.info("  Execution: Margin of Safety / Round Number Retest")
    logger.info("  Feeder: Binance Live WebSocket")
    logger.info("  Destination: PRDT Finance Webhook")
    logger.info("=" * 65)

    # 1. Configuration
    symbols = os.environ.get("TRADING_SYMBOLS", "BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT").split(",")
    symbols = [s.strip() for s in symbols if s.strip()]
    interval = os.environ.get("CANDLE_INTERVAL", "1m")
    expiry_seconds = int(os.environ.get("TRADE_EXPIRY_SECONDS", "300"))

    webhook_url = os.environ.get("PRDT_WEBHOOK_URL", "")
    api_key = os.environ.get("PRDT_API_KEY", "")
    stake_usd = float(os.environ.get("TRADE_STAKE_USD", "10.0"))
    simulation_mode = os.environ.get("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")

    # 2. Instantiate Components
    engine = AssassinSignalEngine(
        doji_threshold=0.10,
        fvg_min_pct=0.01,
        swing_left=2,
        swing_right=2,
        safety_tolerance_pct=0.08,
        default_expiry_seconds=expiry_seconds,
        require_safety_retest=True,
    )

    dispatcher = PRDTWebhookDispatcher(
        webhook_url=webhook_url,
        api_key=api_key,
        default_stake_usd=stake_usd,
        simulation_mode=simulation_mode
    )

    # 3. Define Callback for Closed Candles
    async def on_candle_closed(symbol: str, candle: Candle):
        signals = engine.update_candle(symbol, candle)
        for sig in signals:
            verdict_icon = "🔥" if sig.verdict == "TAKE_IT" else "📊"
            logger.critical(
                f"{verdict_icon} SIGNAL: {sig.symbol} {sig.action.upper()} | "
                f"${sig.price:.2f} | {sig.verdict} ({sig.confidence*100:.0f}%) | "
                f"Solid={sig.solid_count} Soft={sig.soft_count} | "
                f"Regime={sig.regime} | {sig.trigger}"
            )
            # Dispatch to PRDT Webhook
            await dispatcher.dispatch_trade(sig)

    # 4. Start Binance Feed
    feed = BinanceFeed(
        symbols=symbols,
        interval=interval,
        on_candle_closed=on_candle_closed
    )

    try:
        logger.info(f"Armed with symbols: {symbols} on {interval} candles.")
        logger.info(f"PRDT Dispatcher Mode: {'SIMULATION' if simulation_mode else 'LIVE WEBHOOK'}")
        await feed.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Assassin Bot...")
    finally:
        await feed.stop()
        await dispatcher.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
