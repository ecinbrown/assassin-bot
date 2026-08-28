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
import time
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


STATE_FILE = os.path.join(os.path.dirname(__file__), "bot_state.json")

def load_saved_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"balance": 80.4737, "wins": 18, "losses": 0}

def save_state(balance: float, wins: int, losses: int):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"balance": round(balance, 4), "wins": wins, "losses": losses}, f, indent=2)
    except Exception:
        pass


@dataclass
class ActiveTrade:
    symbol: str
    action: str
    entry_price: float
    stake_native: float
    entry_time: float
    expiry_time: float
    epoch: int
    gale_level: int = 0  # 0 = Base, 1 = Gale 1, 2 = Gale 2
    total_sequence_stake: float = 0.0


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

        # Live performance stats (Restored from state)
        saved = load_saved_state()
        self.wins: int = saved.get("wins", 18)
        self.losses: int = saved.get("losses", 0)
        self.marts_since_loss: int = 10  # Starts in Golden Rebound state
        self.is_in_mart_recovery: bool = False
        self.lost_mart_amount: float = 0.0
        self.active_trades: List[ActiveTrade] = []
        self.latest_prices: dict = {}
        
        self.engine: Optional[AssassinSignalEngine] = None
        self.prdt_agent: Optional[PRDTAgent] = None
        self.telegram_bot: Optional[AssassinTelegramBot] = None
        self.dispatcher: Optional[PRDTWebhookDispatcher] = None

    def calculate_dynamic_stake(self, balance: float) -> float:
        """
        Dynamic Compounding Engine (5% Base Stake Scaling + 1-Trade Mart Recovery):
        - If in Mart Recovery mode: sizes stake to recover the entire lost Mart + full target profit in 1 single trade.
        - Otherwise: dynamically calculates 5% base stake as balance compounds.
        """
        if balance <= 0:
            return self.stake_native

        if self.is_in_mart_recovery and self.lost_mart_amount > 0:
            target_profit = balance * 0.05 * 0.88
            rec_stake = round((self.lost_mart_amount + target_profit) / 0.88, 4)
            # Safe risk cap at max 23% of balance
            rec_stake = min(round(balance * 0.23, 4), rec_stake)
            return max(self.stake_native, rec_stake)

        # 5% base stake scaling with a hard minimum floor
        dynamic_stake = round(max(self.stake_native, balance * 0.05), 4)
        return dynamic_stake


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
    tg_token = os.environ.get("ASSASSIN_TG_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "8295109367:AAHeUa5k_eIpl-OQb9LcuOUekBiGL7D8FQQ")
    tg_chat_id = os.environ.get("ASSASSIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "6363315804"

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
    # Restore saved simulated balance if available
    saved_state = load_saved_state()
    prdt_agent.simulated_balance = saved_state.get("balance", 80.4737)
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

        controller.latest_prices[symbol] = candle.close
        now = time.time()

        # Check and settle any completed active trades
        remaining_trades = []
        for t in controller.active_trades:
            if now >= t.expiry_time:
                exit_price = controller.latest_prices.get(t.symbol, candle.close)
                is_win = (exit_price > t.entry_price) if t.action == 'call' else (exit_price < t.entry_price)
                step_name = "BASE" if t.gale_level == 0 else f"GALE {t.gale_level}"

                if is_win:
                    # ─── SEQUENCE WIN (Base or Gale 1) ───
                    controller.wins += 1
                    controller.marts_since_loss += 1
                    gross_payout = round(t.stake_native * 1.88, 4)
                    seq_profit = round(gross_payout - t.total_sequence_stake, 4)
                    prdt_agent.simulated_balance = round(prdt_agent.simulated_balance + gross_payout, 4)
                    save_state(prdt_agent.simulated_balance, controller.wins, controller.losses)

                    # Reset 1-Trade Mart Recovery mode immediately on win -> returns to normal 5% Base!
                    if controller.is_in_mart_recovery:
                        controller.is_in_mart_recovery = False
                        controller.lost_mart_amount = 0.0
                        logger.critical("🎯 [1-TRADE RECOVERY COMPLETE] Loss 100% erased + profit banked! Resetting to normal 5% Base Stake.")

                    outcome_title = "WIN ✅"
                    logger.critical(
                        f"🏆 [SEQUENCE WIN] {t.symbol} {t.action.upper()} ({outcome_title}) | "
                        f"Entry: ${t.entry_price:.2f} -> Exit: ${exit_price:.2f} | "
                        f"Net Profit: {seq_profit:+.4f} Native | "
                        f"Balance: {prdt_agent.simulated_balance:.4f} Native | "
                        f"Score: {controller.wins}W - {controller.losses}L (Streak: {controller.marts_since_loss})"
                    )

                    if tg_bot:
                        await tg_bot.send_settlement_alert(
                            symbol=t.symbol,
                            action=t.action,
                            entry_price=t.entry_price,
                            exit_price=exit_price,
                            is_win=True,
                            profit_loss=seq_profit,
                            new_balance=prdt_agent.simulated_balance if controller.simulation_mode else 0.0,
                            wins=controller.wins,
                            losses=controller.losses,
                            step_info=outcome_title
                        )
                else:
                    # ─── AUTO 1-GALE RECOVERY ENGINE (STRICT MAX GALE 1) ───
                    max_allowed_gale = 1

                    if t.gale_level < max_allowed_gale:
                        next_gale = t.gale_level + 1
                        next_stake = round(t.stake_native * 2.2, 4)
                        # Deduct next stake for simulation
                        prdt_agent.simulated_balance = round(prdt_agent.simulated_balance - next_stake, 4)
                        save_state(prdt_agent.simulated_balance, controller.wins, controller.losses)

                        logger.critical(
                            f"⚡ [GALE {next_gale} TRIGGERED] {t.symbol} {t.action.upper()} | "
                            f"Entry: ${exit_price:.2f} | Stake: {next_stake:.4f} Native | Expiry: 300s"
                        )

                        # Register immediate Gale recovery trade on same coin silently
                        remaining_trades.append(ActiveTrade(
                            symbol=t.symbol,
                            action=t.action.lower(),
                            entry_price=exit_price,
                            stake_native=next_stake,
                            entry_time=now,
                            expiry_time=now + 300,
                            epoch=prdt_agent.get_current_epoch(),
                            gale_level=next_gale,
                            total_sequence_stake=round(t.total_sequence_stake + next_stake, 4)
                        ))
                    else:
                        # ─── SEQUENCE LOSS (GALE 1 CAP - MAX 16% RISK) ───
                        controller.losses += 1
                        controller.marts_since_loss = 0
                        seq_loss = -round(t.total_sequence_stake, 4)
                        
                        # Arm 1-Trade Mart Recovery for the very next signal
                        controller.is_in_mart_recovery = True
                        controller.lost_mart_amount = round(t.total_sequence_stake, 4)
                        logger.warning(
                            f"⚡ [1-TRADE RECOVERY ARMED] Next signal will stake to recover "
                            f"{controller.lost_mart_amount:.4f} Native in 1 single trade."
                        )
                        
                        save_state(prdt_agent.simulated_balance, controller.wins, controller.losses)

                        logger.warning(
                            f"❌ [SEQUENCE LOSS] {t.symbol} {t.action.upper()} missed Gale 1. "
                            f"Total Loss: {seq_loss:+.4f} Native | Score: {controller.wins}W - {controller.losses}L"
                        )

                        if tg_bot:
                            await tg_bot.send_settlement_alert(
                                symbol=t.symbol,
                                action=t.action,
                                entry_price=t.entry_price,
                                exit_price=exit_price,
                                is_win=False,
                                profit_loss=seq_loss,
                                new_balance=prdt_agent.simulated_balance if controller.simulation_mode else 0.0,
                                wins=controller.wins,
                                losses=controller.losses,
                                step_info="LOSS ❌"
                            )
            else:
                remaining_trades.append(t)
        controller.active_trades = remaining_trades

        # Evaluate candle for new 90%+ confluence signals
        signals = engine.update_candle(symbol, candle)
        active_symbols = {t.symbol for t in controller.active_trades}

        for sig in signals:
            # ─── STRICT CONCURRENCY RULE: MAX 2 ACTIVE TRADES ───
            if len(controller.active_trades) >= 2:
                logger.info(
                    f"⏸️ [CONCURRENCY CAP] 2 trades already active ({[t.symbol for t in controller.active_trades]}). "
                    f"Skipping new signal for {sig.symbol}."
                )
                continue

            if sig.symbol in active_symbols:
                logger.info(f"⏸️ [SYMBOL BUSY] {sig.symbol} already has an active trade sequence running. Skipping duplicate signal.")
                continue

            # ─── POST-LOSS STABILIZATION FILTER (Marts +1 & +2 require 4+ Confirmations) ───
            if controller.marts_since_loss < 2:
                if sig.solid_count < 3 and (sig.solid_count + sig.soft_count) < 4:
                    logger.info(
                        f"🛡️ [POST-LOSS STABILIZATION] {sig.symbol} skipped ({sig.solid_count} solid + {sig.soft_count} soft). "
                        f"Requires 4+ confirmations."
                    )
                    continue

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

            # 1. Execute via Dynamic Compounding Staking
            current_balance = prdt_agent.simulated_balance if controller.simulation_mode else prdt_agent.get_balance()
            trade_stake = controller.calculate_dynamic_stake(current_balance)
            success, tx_or_reason = await prdt_agent.execute_trade(sig, stake_native=trade_stake)
            if success:
                logger.info(f"✅ Trade Executed on PRDT Contract (Stake: {trade_stake} Native | Balance: {current_balance:.4f}): {tx_or_reason}")
                # Register active trade for automated outcome tracking
                controller.active_trades.append(ActiveTrade(
                    symbol=sig.symbol,
                    action=sig.action.lower(),
                    entry_price=sig.price,
                    stake_native=trade_stake,
                    entry_time=time.time(),
                    expiry_time=time.time() + sig.expiry_seconds,
                    epoch=prdt_agent.get_current_epoch(),
                    gale_level=0,
                    total_sequence_stake=trade_stake
                ))
                active_symbols.add(sig.symbol)
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

    # Preload historical candles via REST API (Eliminates 15-minute cold start!)
    try:
        logger.info(f"⏳ Pre-loading historical {controller.interval} candles for {controller.symbols}...")
        history_map = await feed.preload_history(limit=50)
        for sym, candles in history_map.items():
            if candles:
                engine.candle_history[sym] = candles
                logger.info(f"🚀 {sym} pre-seeded with {len(candles)} candles. Engine INSTANTLY ARMED!")
    except Exception as e:
        logger.warning(f"Historical preload failed ({e}). Will build history from live feed.")

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
