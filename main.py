"""
Assassin Bot - Main Application Runner v2
==========================================
Full Price-Action Confluence Engine:
Binance Live Feeder → Assassin Confluence Engine → PRDT Finance Web3 Smart Contract
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
    PRDTAgent,
    PRDTWebhookDispatcher
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("AssassinBot")


async def main():
    logger.info("=" * 65)
    logger.info("  ASSASSIN BOT v2 — Real-Market Crypto Confluence Engine")
    logger.info("  ─────────────────────────────────────────────────────")
    logger.info("  Strategies: QM + OB + FVG + Doji + Engulfing + Exhaustion")
    logger.info("  Structure: S/R Zones + Round Numbers + Trendlines")
    logger.info("  Analysis: Regime Detection + 3-Tier Confluence Scoring")
    logger.info("  Execution Engine: Web3 Smart Contract (PRDTAgent)")
    logger.info("  Feeder: Binance Live WebSocket (1m/3m/5m)")
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

    # Optional Webhook fallback URL
    webhook_url = os.environ.get("PRDT_WEBHOOK_URL", "")
    api_key = os.environ.get("PRDT_API_KEY", "")

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

    # Direct Web3 Smart Contract Agent
    prdt_agent = PRDTAgent(
        rpc_url=rpc_url,
        contract_address=contract_addr,
        private_key=private_key,
        default_stake_native=stake_native,
        min_buffer_seconds=20,
        simulation_mode=simulation_mode
    )
    prdt_agent.initialize()

    # Webhook Dispatcher (if configured)
    dispatcher = None
    if webhook_url:
        dispatcher = PRDTWebhookDispatcher(
            webhook_url=webhook_url,
            api_key=api_key,
            default_stake_usd=10.0,
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

            # 1. Execute via Web3 Smart Contract (Method 2)
            success, tx_or_reason = await prdt_agent.execute_trade(sig)
            if success:
                logger.info(f"✅ Trade Executed on PRDT Contract: {tx_or_reason}")
            else:
                logger.warning(f"⚠️ Trade Execution Failed / Skipped: {tx_or_reason}")

            # 2. Also dispatch to Webhook if configured
            if dispatcher:
                await dispatcher.dispatch_trade(sig)

    # 4. Background Auto-Claim Winnings Task (every 60s)
    async def auto_claim_worker():
        while True:
            try:
                await asyncio.sleep(60)
                await prdt_agent.auto_claim_winnings()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Auto-claim tick error: {e}")

    claim_task = asyncio.create_task(auto_claim_worker())

    # 5. Start Binance Feed
    feed = BinanceFeed(
        symbols=symbols,
        interval=interval,
        on_candle_closed=on_candle_closed
    )

    try:
        logger.info(f"Armed with symbols: {symbols} on {interval} candles.")
        logger.info(f"PRDT Smart Contract Mode: {'SIMULATION (Dry-Run)' if prdt_agent.simulation_mode else 'LIVE ON-CHAIN'}")
        await feed.start()
    except KeyboardInterrupt:
        logger.info("Shutting down Assassin Bot...")
    finally:
        claim_task.cancel()
        await feed.stop()
        if dispatcher:
            await dispatcher.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExited.")
