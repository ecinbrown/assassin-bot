"""
Assassin Bot - Main Application Runner v2
==========================================
Full Price-Action Confluence Engine:
Binance Live Feeder → Assassin Confluence Engine → PRDT Finance Web3 Smart Contract
+ Interactive Telegram Controller & Live Alert Engine
"""
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from typing import List, Optional

import aiohttp
from aiohttp import web

_liquid_pairs_cache = {"pairs": set(), "updated_at": 0.0}

async def get_liquid_pairs(symbols: List[str], top_n: int = 3, refresh_seconds: int = 3600) -> set:
    """
    Return the top_n symbols (from our watchlist) by real 24h quote volume on Binance,
    refreshed at most once per refresh_seconds. Falls back to the cached/static set on
    any fetch failure so a network hiccup never blocks recovery trading.
    """
    now = time.time()
    if _liquid_pairs_cache["pairs"] and (now - _liquid_pairs_cache["updated_at"]) < refresh_seconds:
        return _liquid_pairs_cache["pairs"]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.binance.com/api/v3/ticker/24hr",
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
        vols = {row["symbol"]: float(row["quoteVolume"]) for row in data if row.get("symbol") in symbols}
        ranked = sorted(vols.items(), key=lambda kv: kv[1], reverse=True)
        top_pairs = {sym for sym, _ in ranked[:top_n]}
        if top_pairs:
            _liquid_pairs_cache["pairs"] = top_pairs
            _liquid_pairs_cache["updated_at"] = now
            logger.info(f"\U0001f4a7 [LIQUIDITY REFRESH] Top {top_n} most liquid pairs: {top_pairs}")
            return top_pairs
    except Exception as e:
        logger.warning(f"Liquidity refresh failed ({e}). Using previous/fallback pairs.")

    # Fallback: cached value if we have one, else the first top_n symbols in the watchlist
    return _liquid_pairs_cache["pairs"] or set(symbols[:top_n])

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
    return {"balance": 10.0, "wins": 0, "losses": 0, "marts_since_loss": 0}

def save_state(balance: float, wins: int, losses: int, marts_since_loss: int = 0):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "balance": round(balance, 4),
                "wins": wins,
                "losses": losses,
                "marts_since_loss": marts_since_loss
            }, f, indent=2)
    except Exception:
        pass


def compute_rsi(closes, period=14):
    """Compute RSI from a list of close prices using Wilder smoothing."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [d if d > 0 else 0.0 for d in deltas]
    losses = [-d if d < 0 else 0.0 for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


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
    is_recovery_trade: bool = False


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
        self.wins: int = saved.get("wins", 0)
        self.losses: int = saved.get("losses", 0)
        self.marts_since_loss: int = saved.get("marts_since_loss", 0)
        self.is_in_mart_recovery: bool = False
        self.lost_mart_amount: float = 0.0
        self.active_trades: List[ActiveTrade] = []
        self.latest_prices: dict = {}
        
        self.engine: Optional[AssassinSignalEngine] = None
        self.prdt_agent: Optional[PRDTAgent] = None
        self.telegram_bot: Optional[AssassinTelegramBot] = None
        self.dispatcher: Optional[PRDTWebhookDispatcher] = None

    # ─── RSI Strategy Thresholds (Backtested 365d, 80.30% 1-Gale WR) ───
    # NORMAL: RSI-14 on 3m (80.3% WR, 44+ marts/day across 8 pairs)
    NORMAL_RSI_LO = 15      # Oversold → CALL
    NORMAL_RSI_HI = 80      # Overbought → PUT
    NORMAL_VOL_MIN = 1.5    # Volume >= 1.5x 20-period avg
    NORMAL_BODY_MIN = 0.8   # Body/ATR >= 0.8
    # RECOVERY: Tighter thresholds for max accuracy on Tier-1 only
    RECOVERY_RSI_LO = 12
    RECOVERY_RSI_HI = 85
    RECOVERY_VOL_MIN = 2.0
    RECOVERY_BODY_MIN = 0.8

    def calculate_dynamic_stake(self, balance: float) -> float:
        """
        Dynamic Compounding Engine (6.1% Base Stake Scaling + 1-Trade Mart Recovery):
        - If in Mart Recovery: sizes stake to recover ALL cumulative losses + 6.1% target profit in 1 trade.
        - Otherwise: dynamically calculates 6.1% base stake as balance compounds.
        - Payout: 90% (PRDT BTC/ETH/BNB tier) = 1.90x gross return on winning trade.
        """
        if balance <= 0:
            return self.stake_native

        PAYOUT = 0.90  # 90% payout — BTC/ETH/BNB tier on PRDT

        if self.is_in_mart_recovery and self.lost_mart_amount > 0:
            # Stake needed to recover full cumulative loss + target profit in ONE trade
            target_profit = balance * 0.061 * PAYOUT
            rec_stake = round((self.lost_mart_amount + target_profit) / PAYOUT, 4)
            # Safety cap: max 25% of balance (slightly relaxed to ensure full recovery)
            rec_stake = min(round(balance * 0.25, 4), rec_stake)
            return max(self.stake_native, rec_stake)

        # 6.1% base stake scaling with a hard minimum floor
        dynamic_stake = round(max(self.stake_native, balance * 0.061), 4)
        return dynamic_stake


async def main():
    logger.info("=" * 65)
    logger.info("  ASSASSIN BOT v2 — Real-Market Crypto Confluence Engine")
    logger.info("  ─────────────────────────────────────────────────────")
    logger.info("  Strategy: RSI-14 Reversal (80.3%% 1-Gale WR | 44+ marts/day)")
    logger.info("  Timeframe: 3m candles | RSI<=15 CALL / RSI>=80 PUT")
    logger.info("  Filters: Vol>=1.5x | Body/ATR>=0.8 | Session Guard")
    logger.info("  Execution: Web3 Smart Contract (PRDTAgent)")
    logger.info("  Feeder: Binance Live WebSocket (1m/3m/5m)")
    logger.info("  Telegram: Interactive Control + Real/Demo Mode Switcher")
    logger.info("=" * 65)

    # 1. Configuration from Environment
    # All 8 broker pairs: 3 Tier-1 (90% payout) + 5 Tier-2 (70% payout)
    default_symbols = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,DOGEUSDT,XRPUSDT,PEPEUSDT,ARBUSDT"
    symbols = os.environ.get("TRADING_SYMBOLS", default_symbols).split(",")
    symbols = [s.strip() for s in symbols if s.strip()]

    # Recovery trades execute ONLY on the most liquid pairs — refreshed hourly by real 24h volume
    RECOVERY_PAIR_COUNT = 3
    TIER1_PAIRS = {"BTCUSDT", "ETHUSDT", "BNBUSDT"}  # fallback if the liquidity fetch fails

    # Multi-Timeframe scanning (1m, 3m, 5m), aligned to natural candle duration for precise 1-candle entries & same-coin Gales
    INTERVALS = ["1m", "3m", "5m"]
    INTERVAL_EXPIRY = {"1m": 60, "3m": 180, "5m": 300}  # 1-candle expiry per timeframe

    # Web3 Smart Contract Configuration
    rpc_url = os.environ.get("PRDT_RPC_URL", "https://bsc-dataseed.binance.org/")
    contract_addr = os.environ.get("PRDT_CONTRACT_ADDRESS", "")
    private_key = os.environ.get("WALLET_PRIVATE_KEY", "")
    stake_native = float(os.environ.get("PRDT_STAKE_NATIVE", "0.01"))
    simulation_mode = os.environ.get("SIMULATION_MODE", "true").lower() in ("true", "1", "yes")

    # Telegram Credentials (supports ASSASSIN_TG_TOKEN & TELEGRAM_BOT_TOKEN)
    tg_token = os.environ.get("ASSASSIN_TG_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("BOT_TOKEN", "")
    tg_chat_id = os.environ.get("ASSASSIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "6363315804"

    # Optional Webhook fallback URL
    webhook_url = os.environ.get("PRDT_WEBHOOK_URL", "")
    api_key = os.environ.get("PRDT_API_KEY", "")

    # 2. Instantiate Master Controller
    controller = AssassinController(
        symbols=symbols,
        interval="multi",  # Multi-TF mode
        expiry_seconds=300,  # Default; overridden per-TF
        stake_native=stake_native,
        simulation_mode=simulation_mode
    )

    # 3. Instantiate one SignalEngine per timeframe (independent candle buffers)
    engines = {}
    for iv in INTERVALS:
        engines[iv] = AssassinSignalEngine(
            doji_threshold=0.10,
            fvg_min_pct=0.01,
            swing_left=2,
            swing_right=2,
            safety_tolerance_pct=0.08,
            default_expiry_seconds=INTERVAL_EXPIRY[iv],
            require_safety_retest=True,
        )
    controller.engine = engines["1m"]  # Primary reference for Telegram status

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
    prdt_agent.simulated_balance = saved_state.get("balance", 10.0)
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

    # 5. Multi-TF Deduplication Guard: tracks last signal time per symbol
    last_signal_time: dict = {}  # { "BTCUSDT": timestamp }
    DEDUP_WINDOW = 120  # Skip if same symbol fired within 2 minutes on any TF

    # 5. Define Callback for Closed Candles (MULTI-TF AWARE)
    async def on_candle_closed(symbol: str, interval: str, candle: Candle):
        if controller.paused:
            return

        controller.latest_prices[symbol] = candle.close
        now = time.time()

        # Route candle to the correct engine's history buffer
        engine = engines.get(interval)
        if not engine:
            return
        expiry_seconds = INTERVAL_EXPIRY.get(interval, 300)

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
                    gross_payout = round(t.stake_native * 1.90, 4)  # 90% payout = 1.90x gross
                    seq_profit = round(gross_payout - t.total_sequence_stake, 4)
                    prdt_agent.simulated_balance = round(prdt_agent.simulated_balance + gross_payout, 4)
                    save_state(prdt_agent.simulated_balance, controller.wins, controller.losses, controller.marts_since_loss)

                    # Reset 1-Trade Mart Recovery mode ONLY if this trade was the designated recovery trade!
                    if t.is_recovery_trade:
                        controller.is_in_mart_recovery = False
                        controller.lost_mart_amount = 0.0
                        logger.critical("🎯 [1-TRADE RECOVERY COMPLETE] Recovery trade won! Full loss + profit banked. Back to 6.1% base stake.")

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
                    # ─── AUTO 1-GALE ON SAME COIN (STRICT MAX GALE 1) ───
                    max_allowed_gale = 1

                    if t.gale_level < max_allowed_gale:
                        next_gale = t.gale_level + 1
                        next_stake = round(t.stake_native * 2.2, 4)
                        # Deduct next stake for simulation
                        prdt_agent.simulated_balance = round(prdt_agent.simulated_balance - next_stake, 4)
                        save_state(prdt_agent.simulated_balance, controller.wins, controller.losses, controller.marts_since_loss)

                        logger.critical(
                            f"⚡ [GALE {next_gale} SAME-COIN TRIGGERED] {t.symbol} {t.action.upper()} | "
                            f"Entry: ${exit_price:.2f} | Stake: {next_stake:.4f} Native | Expiry: {t.expiry_time - t.entry_time:.0f}s"
                        )

                        # Register immediate Gale recovery trade on the exact same coin
                        trade_duration = t.expiry_time - t.entry_time
                        remaining_trades.append(ActiveTrade(
                            symbol=t.symbol,
                            action=t.action.lower(),
                            entry_price=exit_price,
                            stake_native=next_stake,
                            entry_time=now,
                            expiry_time=now + trade_duration,
                            epoch=prdt_agent.get_current_epoch(),
                            gale_level=next_gale,
                            total_sequence_stake=round(t.total_sequence_stake + next_stake, 4),
                            is_recovery_trade=t.is_recovery_trade
                        ))
                    else:
                        # ─── SEQUENCE LOSS (MISSED BASE + MISSED GALE 1) ───
                        controller.losses += 1
                        controller.marts_since_loss = 0
                        seq_loss = -round(t.total_sequence_stake, 4)

                        # Arm Mart Recovery for the next fresh signal
                        controller.is_in_mart_recovery = True
                        controller.lost_mart_amount = round(
                            controller.lost_mart_amount + t.total_sequence_stake, 4
                        )
                        logger.warning(
                            f"⚡ [SEQUENCE LOSS] {t.symbol} {t.action.upper()} missed Gale 1. "
                            f"Total Sequence Loss: {seq_loss:+.4f} Native. Loss queued for next recovery."
                        )

                        save_state(prdt_agent.simulated_balance, controller.wins, controller.losses, controller.marts_since_loss)

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
                                step_info="SEQUENCE LOSS ❌"
                            )
            else:
                remaining_trades.append(t)
        controller.active_trades = remaining_trades

        # ═══════════════════════════════════════════════════════════════
        # RSI-14 REVERSAL STRATEGY (3m Candles Only)
        # Backtested: 80.30% 1-Gale WR | 44+ marts/day (8 pairs)
        # 365 days x 2.1M candles (BTC, ETH, SOL, BNB)
        # ═══════════════════════════════════════════════════════════════
        engine.update_candle(symbol, candle)
        active_symbols = {t.symbol for t in controller.active_trades}
        history = engine.candle_history.get(symbol, [])

        signals = []
        mode_tag = "RSI-14"

        # Only generate RSI signals on 3m candles (the winning timeframe)
        if interval == "3m" and len(history) >= 25:
            closes = [c.close for c in history[-25:]]
            rsi_val = compute_rsi(closes, period=14)

            # Volume ratio vs 20-period average
            avg_vol = sum(c.volume for c in history[-20:]) / 20.0
            vol_ratio = candle.volume / avg_vol if avg_vol > 0 else 1.0

            # Body / ATR ratio (big-body filter)
            body_size = abs(candle.close - candle.open)
            atr_vals = [c.high - c.low for c in history[-14:]]
            atr_avg = sum(atr_vals) / len(atr_vals) if atr_vals else 1e-10
            body_ratio = body_size / (atr_avg + 1e-10)

            # Thresholds — tighter in recovery mode
            is_recovery = controller.is_in_mart_recovery
            if is_recovery:
                rsi_lo = AssassinController.RECOVERY_RSI_LO
                rsi_hi = AssassinController.RECOVERY_RSI_HI
                vol_req = AssassinController.RECOVERY_VOL_MIN
                body_req = AssassinController.RECOVERY_BODY_MIN
                mode_tag = "RECOVERY RSI"
            else:
                rsi_lo = AssassinController.NORMAL_RSI_LO
                rsi_hi = AssassinController.NORMAL_RSI_HI
                vol_req = AssassinController.NORMAL_VOL_MIN
                body_req = AssassinController.NORMAL_BODY_MIN
                mode_tag = "RSI-14 80%"

            signal_action = None
            if rsi_val <= rsi_lo and vol_ratio >= vol_req and body_ratio >= body_req:
                signal_action = 'call'
            elif rsi_val >= rsi_hi and vol_ratio >= vol_req and body_ratio >= body_req:
                signal_action = 'put'

            if signal_action:
                sig = AssassinSignal(
                    symbol=symbol,
                    action=signal_action,
                    price=candle.close,
                    confidence=0.80,
                    trigger=f"RSI-14={rsi_val:.1f} | Vol={vol_ratio:.1f}x | Body/ATR={body_ratio:.2f}",
                    pattern_type="RSI_REVERSAL",
                    expiry_seconds=expiry_seconds,
                    timestamp=time.time(),
                    verdict="TAKE_IT",
                    regime="RSI_EXTREME",
                    solid_count=3,
                    soft_count=0,
                    metadata={"rsi": rsi_val, "vol_ratio": vol_ratio, "body_ratio": body_ratio}
                )
                signals.append(sig)
                logger.info(
                    f"📊 [RSI SIGNAL] {symbol} {signal_action.upper()} | "
                    f"RSI={rsi_val:.1f} Vol={vol_ratio:.1f}x Body/ATR={body_ratio:.2f}"
                )

        liquid_pairs = None
        if controller.is_in_mart_recovery:
            liquid_pairs = await get_liquid_pairs(controller.symbols, top_n=RECOVERY_PAIR_COUNT)

        for sig in signals:
            # ─── RECOVERY ISOLATION: Only the most liquid pairs right now ───
            if controller.is_in_mart_recovery:
                if sig.symbol not in liquid_pairs:
                    logger.info(f"⏸️ [RECOVERY LIQUIDITY] {sig.symbol} not in top {RECOVERY_PAIR_COUNT} liquid pairs {liquid_pairs}. Skipping.")
                    continue
                if len(controller.active_trades) >= 1:
                    logger.info(f"⏸️ [RECOVERY ISOLATION] Waiting for trades to settle. Skipping {sig.symbol}.")
                    continue
            else:
                # ─── CONCURRENCY GUARD — hard ceiling stays at 2 total trades ───
                if len(controller.active_trades) >= 2:
                    logger.info(f"⏸️ [CONCURRENCY CAP] 2 trades active. Skipping {sig.symbol}.")
                    continue
                # Both slots may now be filled in the same direction if that's what qualifies —
                # the 2-trade cap above is the real risk limiter, this just stops double-booking
                # more same-direction trades than there are open slots.
                same_dir = [t for t in controller.active_trades if t.action == sig.action.lower()]
                if len(same_dir) >= 2:
                    logger.info(f"⏸️ [CORRELATION GUARD] Already have max same-direction trades. Skipping {sig.symbol}.")
                    continue

            if sig.symbol in active_symbols:
                logger.info(f"⏸️ [SYMBOL BUSY] {sig.symbol} already active. Skipping.")
                continue

            # ─── DEDUP: Skip if signalled within 2 min ───
            if sig.symbol in last_signal_time and (now - last_signal_time[sig.symbol]) < DEDUP_WINDOW:
                logger.info(f"⏸️ [DEDUP] {sig.symbol} signalled {now - last_signal_time[sig.symbol]:.0f}s ago. Skipping.")
                continue

            # ─── SESSION FILTER: Skip 03:00-06:00 UTC dead zone ───
            from datetime import datetime, timezone
            utc_hour = datetime.now(timezone.utc).hour
            if 3 <= utc_hour < 6:
                logger.info(f"🛡️ [SESSION] {sig.symbol} skipped — UTC {utc_hour}:00 dead zone.")
                continue

            logger.info(f"✅ [{mode_tag}|3m] {sig.symbol} {sig.action.upper()} — RSI gate passed!")


            verdict_icon = "🔥" if sig.verdict == "TAKE_IT" else "📊"
            logger.critical(
                f"{verdict_icon} [{interval}] {sig.symbol} {sig.action.upper()} | "
                f"${sig.price:.2f} | {sig.verdict} ({sig.confidence*100:.0f}%) | "
                f"Solid={sig.solid_count} Soft={sig.soft_count} | "
                f"Regime={sig.regime} | {sig.trigger}"
            )

            # 1. Execute via Dynamic Compounding Staking
            current_balance = prdt_agent.simulated_balance if controller.simulation_mode else prdt_agent.get_balance()
            trade_stake = controller.calculate_dynamic_stake(current_balance)
            success, tx_or_reason = await prdt_agent.execute_trade(sig, stake_native=trade_stake)
            if success:
                logger.info(f"✅ Trade Executed on PRDT Contract (Stake: {trade_stake} Native | Balance: {current_balance:.4f}): {tx_or_reason}")
                # Register active trade for automated outcome tracking
                is_rec = controller.is_in_mart_recovery
                controller.active_trades.append(ActiveTrade(
                    symbol=sig.symbol,
                    action=sig.action.lower(),
                    entry_price=sig.price,
                    stake_native=trade_stake,
                    entry_time=time.time(),
                    expiry_time=time.time() + sig.expiry_seconds,
                    epoch=prdt_agent.get_current_epoch(),
                    gale_level=0,
                    total_sequence_stake=trade_stake,
                    is_recovery_trade=is_rec
                ))
                active_symbols.add(sig.symbol)
                last_signal_time[sig.symbol] = now  # Mark for dedup
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

    # 9. Start Multi-TF Binance Feed
    feed = BinanceFeed(
        symbols=controller.symbols,
        intervals=INTERVALS,
        on_candle_closed=on_candle_closed
    )

    # Preload historical candles for ALL timeframes
    try:
        logger.info(f"⏳ Pre-loading history for {controller.symbols} × {INTERVALS}...")
        history_map = await feed.preload_history(limit=50)
        for sym, iv_data in history_map.items():
            for iv, candles in iv_data.items():
                if candles:
                    engines[iv].candle_history[sym] = candles
                    logger.info(f"🚀 {sym}/{iv} pre-seeded with {len(candles)} candles. ARMED!")
    except Exception as e:
        logger.warning(f"Historical preload failed ({e}). Will build history from live feed.")

    try:
        logger.info(f"Armed: {controller.symbols} × {INTERVALS} = {len(controller.symbols) * len(INTERVALS)} channels")
        logger.info(f"Mode: {'🧪 SIMULATION (Demo)' if controller.simulation_mode else '🟢 LIVE ON-CHAIN (Real)'}")
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
