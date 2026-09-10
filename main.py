"""
Assassin Bot - Main Application Runner v3.1
=============================================
RSI-7 Reversal Strategy (Backtest-Proven: 80.6% Mart SeqWR | ~16/day)
Binance Live Feeder → RSI-7 Signal Engine → PRDT Finance Web3 Smart Contract
+ Interactive Telegram Controller & Live Alert Engine

Winning Config (365d backtest, 5972 signals, honest mart-sequence counting):
  RSI period=7 | lo≤20 CALL / hi≥72 PUT | Vol≥2.5x | Body/ATR≥0.5
  3-candle cooldown | NO counter-trend filter | BTC+ETH ONLY (90% payout)
  
Nuance-validated (validate_v3_nuances.py):
  - RSI window: 50 closes (0.03% mismatch vs full history)
  - BTC EV: +0.1164×stake | ETH EV: +0.1322×stake
  - BNB/SOL/70% pairs: NEGATIVE EV, excluded
  - Session filter: REMOVED (dead zone has 81.1% WR, better than avg)
  - Concurrency cap: 0.4% impact, negligible
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


def compute_rsi(closes, period=7):
    """Compute RSI from a list of close prices using Wilder smoothing.
    Default period=7 (backtest-proven optimal for 3m candles)."""
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

    # ─── RSI-7 Strategy Thresholds (Nuance-validated: 80.6% Mart SeqWR, ~16/day) ───
    # BTC+ETH ONLY (90% payout, positive dollar EV)
    # 70% payout pairs (BNB/SOL/DOGE/XRP/PEPE) have NEGATIVE EV — excluded
    RSI_PERIOD = 7          # RSI period (7 = faster, more signals than RSI-14)
    RSI_HISTORY = 50        # Use 50 closes for RSI (0.03% mismatch vs full history)
    NORMAL_RSI_LO = 20      # Oversold → CALL  (RSI-7 ≤ 20)
    NORMAL_RSI_HI = 72      # Overbought → PUT  (RSI-7 ≥ 72)
    NORMAL_VOL_MIN = 2.5    # Volume >= 2.5x 20-period avg
    NORMAL_BODY_MIN = 0.5   # Body/ATR >= 0.5
    SIGNAL_COOLDOWN = 3     # Min 3 candles between signals on same symbol
    USE_COUNTER_TREND = False  # Backtest: ct=none outperformed ct=counter
    # RECOVERY: Same thresholds as normal (tightening removed - was causing
    # multi-hour silence after every loss with little accuracy benefit)
    RECOVERY_RSI_LO = NORMAL_RSI_LO
    RECOVERY_RSI_HI = NORMAL_RSI_HI
    RECOVERY_VOL_MIN = NORMAL_VOL_MIN
    RECOVERY_BODY_MIN = NORMAL_BODY_MIN
    # Pair payout tiers (from live platform)
    PAIR_PAYOUTS = {
        "BTCUSDT": 0.90, "ETHUSDT": 0.90,
        "BNBUSDT": 0.70, "SOLUSDT": 0.70,
        "DOGEUSDT": 0.70, "XRPUSDT": 0.70, "PEPEUSDT": 0.70,
    }
    # ONLY trade pairs with positive dollar EV (90% payout, raw WR > 52.6%)
    TRADEABLE_PAIRS = {"BTCUSDT", "ETHUSDT"}  # 80.6% SeqWR, EV +0.12/+0.13
    TIER1_PAIRS = {"BTCUSDT", "ETHUSDT"}      # Recovery also BTC/ETH only

    def calculate_dynamic_stake(self, balance: float, symbol: str = "BTCUSDT") -> float:
        """
        Dynamic Compounding Engine (6.1% Base Stake Scaling + 1-Trade Mart Recovery):
        - If in Mart Recovery: sizes stake to recover ALL cumulative losses + 6.1% target profit in 1 trade.
        - Otherwise: dynamically calculates 6.1% base stake as balance compounds.
        - Payout: per-pair from PAIR_PAYOUTS (90% BTC/ETH, 70% others).
        """
        if balance <= 0:
            return self.stake_native

        payout = self.PAIR_PAYOUTS.get(symbol, 0.70)

        if self.is_in_mart_recovery and self.lost_mart_amount > 0:
            # Stake needed to recover full cumulative loss + target profit in ONE trade
            target_profit = balance * 0.061 * payout
            rec_stake = round((self.lost_mart_amount + target_profit) / payout, 4)
            # Safety cap: max 25% of balance (slightly relaxed to ensure full recovery)
            rec_stake = min(round(balance * 0.25, 4), rec_stake)
            return max(self.stake_native, rec_stake)

        # 6.1% base stake scaling with a hard minimum floor
        dynamic_stake = round(max(self.stake_native, balance * 0.061), 4)
        return dynamic_stake


async def main():
    logger.info("=" * 65)
    logger.info("  ASSASSIN BOT v3.1 — RSI-7 Reversal Engine (Nuance-Fixed)")
    logger.info("  ─────────────────────────────────────────────────────")
    logger.info("  Strategy: RSI-7 Reversal (80.6%% Mart SeqWR | ~16/day)")
    logger.info("  Timeframe: 3m candles | RSI-7<=20 CALL / RSI-7>=72 PUT")
    logger.info("  Filters: Vol>=2.5x | Body/ATR>=0.5 | NO Counter-Trend")
    logger.info("  Guards: 3-candle cooldown | NO session filter")
    logger.info("  Pairs: BTC(90%%) + ETH(90%%) ONLY (positive $ EV)")
    logger.info("  Excluded: BNB/SOL/DOGE/XRP/PEPE (70%% payout = negative EV)")
    logger.info("  Execution: Web3 Smart Contract (PRDTAgent)")
    logger.info("  Feeder: Binance Live WebSocket (3m)")
    logger.info("  Telegram: Interactive Control + Real/Demo Mode Switcher")
    logger.info("=" * 65)

    # 1. Configuration from Environment
    # Trade ONLY BTC+ETH (90% payout = positive dollar EV)
    # Monitor all 7 pairs on feed, but only generate signals on TRADEABLE_PAIRS
    default_symbols = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,DOGEUSDT,XRPUSDT,PEPEUSDT"
    symbols = os.environ.get("TRADING_SYMBOLS", default_symbols).split(",")
    symbols = [s.strip() for s in symbols if s.strip()]

    # Recovery trades execute ONLY on the most liquid pairs — refreshed hourly by real 24h volume
    RECOVERY_PAIR_COUNT = 3
    TIER1_PAIRS = AssassinController.TIER1_PAIRS  # BTC/ETH — positive EV proven

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
    DEDUP_WINDOW = 30  # Reduced from 120s — 3-candle cooldown already handles spacing

    # 5b. Per-symbol candle cooldown: tracks last signal candle index per symbol
    last_signal_candle: dict = {}  # { "BTCUSDT": candle_count_at_last_signal }

    # 5a. Background Trade Settler — runs every 5s independently of candle callbacks
    #     Prevents zombie trades from blocking the concurrency guard forever
    async def background_trade_settler():
        while True:
            try:
                await asyncio.sleep(5)
                if controller.paused or not controller.active_trades:
                    continue
                now = time.time()
                remaining = []
                for t in controller.active_trades:
                    if now >= t.expiry_time:
                        # Use latest known price for settlement
                        exit_price = controller.latest_prices.get(t.symbol, t.entry_price)
                        is_win = (exit_price > t.entry_price) if t.action == 'call' else (exit_price < t.entry_price)
                        step_name = "BASE" if t.gale_level == 0 else f"GALE {t.gale_level}"

                        if is_win:
                            controller.wins += 1
                            controller.marts_since_loss += 1
                            pair_payout = AssassinController.PAIR_PAYOUTS.get(t.symbol, 0.70)
                            gross_payout = round(t.stake_native * (1.0 + pair_payout), 4)
                            seq_profit = round(gross_payout - t.total_sequence_stake, 4)
                            prdt_agent.simulated_balance = round(prdt_agent.simulated_balance + gross_payout, 4)
                            if t.is_recovery_trade:
                                controller.is_in_mart_recovery = False
                                controller.lost_mart_amount = 0.0
                            save_state(prdt_agent.simulated_balance, controller.wins, controller.losses, controller.marts_since_loss)
                            logger.critical(f"[BG-SETTLER] WIN {t.symbol} {t.action.upper()} {step_name} | Profit: {seq_profit:+.4f} | Bal: {prdt_agent.simulated_balance:.4f}")
                            if tg_bot:
                                await tg_bot.send_settlement_alert(
                                    symbol=t.symbol, action=t.action,
                                    entry_price=t.entry_price, exit_price=exit_price,
                                    is_win=True, profit_loss=seq_profit,
                                    new_balance=prdt_agent.simulated_balance if controller.simulation_mode else 0.0,
                                    wins=controller.wins, losses=controller.losses, step_info=f"WIN {step_name}"
                                )
                        else:
                            max_allowed_gale = 1
                            if t.gale_level < max_allowed_gale:
                                next_gale = t.gale_level + 1
                                next_stake = round(t.stake_native * 2.2, 4)
                                prdt_agent.simulated_balance = round(prdt_agent.simulated_balance - next_stake, 4)
                                save_state(prdt_agent.simulated_balance, controller.wins, controller.losses, controller.marts_since_loss)
                                trade_duration = t.expiry_time - t.entry_time
                                remaining.append(ActiveTrade(
                                    symbol=t.symbol, action=t.action.lower(),
                                    entry_price=exit_price, stake_native=next_stake,
                                    entry_time=now, expiry_time=now + trade_duration,
                                    epoch=prdt_agent.get_current_epoch(),
                                    gale_level=next_gale,
                                    total_sequence_stake=round(t.total_sequence_stake + next_stake, 4),
                                    is_recovery_trade=t.is_recovery_trade
                                ))
                                logger.critical(f"[BG-SETTLER] GALE {next_gale} triggered {t.symbol} {t.action.upper()} | Stake: {next_stake:.4f}")
                            else:
                                controller.losses += 1
                                controller.marts_since_loss = 0
                                controller.is_in_mart_recovery = True
                                controller.lost_mart_amount = round(controller.lost_mart_amount + t.total_sequence_stake, 4)
                                save_state(prdt_agent.simulated_balance, controller.wins, controller.losses, controller.marts_since_loss)
                                logger.warning(f"[BG-SETTLER] SEQ LOSS {t.symbol} {t.action.upper()} | Lost: {t.total_sequence_stake:.4f}")
                                if tg_bot:
                                    await tg_bot.send_settlement_alert(
                                        symbol=t.symbol, action=t.action,
                                        entry_price=t.entry_price, exit_price=exit_price,
                                        is_win=False, profit_loss=-t.total_sequence_stake,
                                        new_balance=prdt_agent.simulated_balance if controller.simulation_mode else 0.0,
                                        wins=controller.wins, losses=controller.losses, step_info="SEQUENCE LOSS"
                                    )
                    else:
                        remaining.append(t)
                controller.active_trades = remaining
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[BG-SETTLER] Error: {e}")

    settler_task = asyncio.create_task(background_trade_settler())

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
                    pair_payout = AssassinController.PAIR_PAYOUTS.get(t.symbol, 0.70)
                    gross_payout = round(t.stake_native * (1.0 + pair_payout), 4)
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
        # RSI-7 REVERSAL STRATEGY (3m Candles Only)
        # Backtest-proven: 80.1% Mart SeqWR | ~46 trades/day (T1 pairs)
        # 365 days x 8333 signals (BTC, ETH, BNB)
        # Filters: RSI-7<=20/>=72, vol>=2.5x, body/ATR>=0.5,
        #          NO counter-trend, 3-candle cooldown
        # ═══════════════════════════════════════════════════════════════
        engine.update_candle(symbol, candle)
        active_symbols = {t.symbol for t in controller.active_trades}
        history = engine.candle_history.get(symbol, [])

        signals = []
        mode_tag = "RSI-7"

        # Only generate RSI signals on 3m candles (the winning timeframe)
        # Only fire on TRADEABLE pairs (BTC+ETH = positive dollar EV)
        if interval == "3m" and len(history) >= 50 and symbol in AssassinController.TRADEABLE_PAIRS:
            closes = [c.close for c in history[-50:]]  # need 50 for EMA50
            # Use 50 closes for RSI to match backtest accuracy (0.03% mismatch)
            rsi_val = compute_rsi(closes[-AssassinController.RSI_HISTORY:], period=AssassinController.RSI_PERIOD)

            # Volume ratio vs 20-period average
            avg_vol = sum(c.volume for c in history[-20:]) / 20.0
            vol_ratio = candle.volume / avg_vol if avg_vol > 0 else 1.0

            # Body / ATR ratio (big-body filter)
            body_size = abs(candle.close - candle.open)
            atr_vals = [c.high - c.low for c in history[-14:]]
            atr_avg = sum(atr_vals) / len(atr_vals) if atr_vals else 1e-10
            body_ratio = body_size / (atr_avg + 1e-10)

            # EMA20 / EMA50 for counter-trend filter
            import numpy as np
            closes_arr = np.array(closes, dtype=float)
            alpha20 = 2.0 / 21.0
            alpha50 = 2.0 / 51.0
            ema20 = closes_arr[0]
            ema50 = closes_arr[0]
            for px in closes_arr[1:]:
                ema20 = alpha20 * px + (1 - alpha20) * ema20
                ema50 = alpha50 * px + (1 - alpha50) * ema50

            # Thresholds — tighter in recovery mode
            is_recovery = controller.is_in_mart_recovery
            if is_recovery:
                rsi_lo = AssassinController.RECOVERY_RSI_LO
                rsi_hi = AssassinController.RECOVERY_RSI_HI
                vol_req = AssassinController.RECOVERY_VOL_MIN
                body_req = AssassinController.RECOVERY_BODY_MIN
                mode_tag = "RECOVERY RSI-7"
            else:
                rsi_lo = AssassinController.NORMAL_RSI_LO
                rsi_hi = AssassinController.NORMAL_RSI_HI
                vol_req = AssassinController.NORMAL_VOL_MIN
                body_req = AssassinController.NORMAL_BODY_MIN
                mode_tag = "RSI-7 80%"

            signal_action = None
            if rsi_val <= rsi_lo and vol_ratio >= vol_req and body_ratio >= body_req:
                signal_action = 'call'
            elif rsi_val >= rsi_hi and vol_ratio >= vol_req and body_ratio >= body_req:
                signal_action = 'put'

            # ─── COUNTER-TREND FILTER (DISABLED — backtest: ct=none wins) ───
            # Kept as dead code for reference / easy re-enable via USE_COUNTER_TREND
            if AssassinController.USE_COUNTER_TREND:
                if signal_action == 'call' and ema20 > ema50:
                    logger.debug(f"[TREND FILTER] {symbol} CALL blocked — EMA20 > EMA50 (uptrend, not counter-trend)")
                    signal_action = None
                elif signal_action == 'put' and ema20 < ema50:
                    logger.debug(f"[TREND FILTER] {symbol} PUT blocked — EMA20 < EMA50 (downtrend, not counter-trend)")
                    signal_action = None

            # ─── COOLDOWN FILTER ───
            # Min 3 candles between signals on same symbol
            candle_idx = engine.candle_counts.get(symbol, 0)
            cooldown = AssassinController.SIGNAL_COOLDOWN
            if signal_action and cooldown > 0:
                last_idx = last_signal_candle.get(symbol, -999)
                if (candle_idx - last_idx) < cooldown:
                    logger.debug(f"[COOLDOWN] {symbol} — only {candle_idx - last_idx} candles since last signal (need {cooldown})")
                    signal_action = None

            # Debug visibility
            trend_tag = 'UP' if ema20 > ema50 else 'DOWN'
            logger.info(
                f"\U0001f50d [RSI CHECK] {symbol} | RSI={rsi_val:.1f} (need <={rsi_lo} or >={rsi_hi}) | "
                f"Vol={vol_ratio:.2f}x (need >={vol_req}) | Body/ATR={body_ratio:.2f} (need >={body_req}) | "
                f"Trend={trend_tag} | {'SIGNAL' if signal_action else 'no signal'}"
            )

            if signal_action:
                last_signal_candle[symbol] = candle_idx
                sig = AssassinSignal(
                    symbol=symbol,
                    action=signal_action,
                    price=candle.close,
                    confidence=0.801,
                    trigger=f"RSI-7={rsi_val:.1f} | Vol={vol_ratio:.1f}x | Body/ATR={body_ratio:.2f} | Trend={trend_tag}",
                    pattern_type="RSI_REVERSAL",
                    expiry_seconds=expiry_seconds,
                    timestamp=time.time(),
                    verdict="TAKE_IT",
                    regime="RSI_EXTREME",
                    solid_count=3,
                    soft_count=0,
                    metadata={"rsi": rsi_val, "vol_ratio": vol_ratio, "body_ratio": body_ratio, "ema_trend": trend_tag}
                )
                signals.append(sig)
                logger.info(
                    f"📊 [RSI SIGNAL] {symbol} {signal_action.upper()} | "
                    f"RSI={rsi_val:.1f} Vol={vol_ratio:.1f}x Body/ATR={body_ratio:.2f} Trend={trend_tag}"
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
                # Only block if a BASE trade (gale_level==0) is active in recovery
                base_trades = [t for t in controller.active_trades if t.gale_level == 0]
                if len(base_trades) >= 1:
                    logger.info(f"⏸️ [RECOVERY ISOLATION] Waiting for base trade to settle. Skipping {sig.symbol}.")
                    continue
            else:
                # ─── CONCURRENCY GUARD — count only base-level trades (gales don't block new signals) ───
                base_trades = [t for t in controller.active_trades if t.gale_level == 0]
                if len(base_trades) >= 2:
                    logger.info(f"⏸️ [CONCURRENCY CAP] 2 base trades active. Skipping {sig.symbol}.")
                    continue

            if sig.symbol in active_symbols:
                logger.info(f"⏸️ [SYMBOL BUSY] {sig.symbol} already active. Skipping.")
                continue

            # ─── DEDUP: Skip if signalled within 2 min ───
            if sig.symbol in last_signal_time and (now - last_signal_time[sig.symbol]) < DEDUP_WINDOW:
                logger.info(f"⏸️ [DEDUP] {sig.symbol} signalled {now - last_signal_time[sig.symbol]:.0f}s ago. Skipping.")
                continue

            # ─── SESSION FILTER: DISABLED ───
            # Nuance validation showed 03-06 UTC has 81.1% SeqWR (BETTER than avg 79.8%)
            # Keeping filter disabled = more signals + better WR
            # from datetime import datetime, timezone
            # utc_hour = datetime.now(timezone.utc).hour
            # if 3 <= utc_hour < 6:
            #     logger.info(f"🛡️ [SESSION] {sig.symbol} skipped")
            #     continue

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
            trade_stake = controller.calculate_dynamic_stake(current_balance, symbol=sig.symbol)
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
        settler_task.cancel()
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
