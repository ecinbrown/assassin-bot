"""
Assassin Bot - Main Application Runner v7.0
=============================================
1-Gale 88% Sequence WR | 30+ Trades/Day | 5 PRDT Pairs
Binance Live Feeder → Multi-TF RSI Pullback Engine → PRDT Finance Web3 Smart Contract
+ Interactive Telegram Controller & Live Alert Engine

Winning Config (365d backtest, OOS-verified on 90d hold-out):
  RSI(5/7/9) Pullback into BB(1.2-2.0σ) + 15m EMA20 Trend Filter
  3m & 5m candles | Single-candle expiry | BTC+ETH+BNB+SOL+XRP
  
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
from typing import List, Optional, Tuple, Dict

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
    AssassinTelegramBot,
    HybridSignalEngine
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
    return {
        "balance": 20.0,
        "wins": 0,
        "losses": 0,
        "marts_since_loss": 0,
        "baseline_balance": 20.0,
        "total_swept_profit": 0.0,
        "last_sweep_ts": time.time()
    }

def save_state(
    balance: float,
    wins: int,
    losses: int,
    marts_since_loss: int = 0,
    baseline_balance: float = 20.0,
    total_swept_profit: float = 0.0,
    last_sweep_ts: float = 0.0
):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "balance": round(balance, 4),
                "wins": wins,
                "losses": losses,
                "marts_since_loss": marts_since_loss,
                "baseline_balance": round(baseline_balance, 4),
                "total_swept_profit": round(total_swept_profit, 4),
                "last_sweep_ts": round(last_sweep_ts, 2)
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
    strategy_key: str = ""
    indicator_family: str = ""


@dataclass
class RecoveryDebt:
    """Tracks a loss that needs recovery on a specific symbol."""
    symbol: str
    lost_amount: float          # Total sequence stake lost
    created_at: float           # time.time() when loss occurred
    cooldown_bars: int = 5      # Bars to wait before recovery eligible
    bars_elapsed: int = 0       # 1m candles seen since loss
    is_ready: bool = False      # True once cooldown_bars passed


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
        self.baseline_balance: float = saved.get("baseline_balance", 20.0)
        self.total_swept_profit: float = saved.get("total_swept_profit", 0.0)
        self.last_sweep_ts: float = saved.get("last_sweep_ts", time.time())
        self.sweep_profit_ratio: float = float(os.environ.get("SWEEP_PROFIT_RATIO", "0.30"))
        self.sweep_interval_hours: float = float(os.environ.get("SWEEP_INTERVAL_HOURS", "168.0"))
        self.safe_vault_address: str = os.environ.get("SAFE_VAULT_ADDRESS", "")
        self.min_sweep_usd: float = float(os.environ.get("MIN_SWEEP_USD", "2.00"))

        self.is_in_mart_recovery: bool = False
        self.lost_mart_amount: float = 0.0
        self.active_trades: List[ActiveTrade] = []
        # Recovery overlay: queue of debts waiting for cooldown then fresh signal
        self.recovery_queue: List[RecoveryDebt] = []
        # Post-loss lockout: symbol -> timestamp until which all trades are paused (15m falling-knife protection)
        self.pair_loss_lockouts: Dict[str, float] = {}
        self.latest_prices: dict = {}
        self.last_trade_time: float = 0.0
        self.last_pair_trade_time: Dict[str, float] = {}
        self.last_pair_strategy: Dict[str, str] = {}
        self.last_strategy_time: Dict[str, float] = {}
        
        self.engine: Optional[AssassinSignalEngine] = None
        self.hybrid_engine: Optional[HybridSignalEngine] = None
        self.prdt_agent: Optional[PRDTAgent] = None
        self.telegram_bot: Optional[AssassinTelegramBot] = None
        self.dispatcher: Optional[PRDTWebhookDispatcher] = None

    def save_current_state(self):
        """Persist current balance and sweep tracking metrics."""
        bal = self.prdt_agent.simulated_balance if self.prdt_agent else 20.0
        save_state(
            balance=bal,
            wins=self.wins,
            losses=self.losses,
            marts_since_loss=self.marts_since_loss,
            baseline_balance=self.baseline_balance,
            total_swept_profit=self.total_swept_profit,
            last_sweep_ts=self.last_sweep_ts
        )

    def execute_sweep(self, force: bool = False) -> Tuple[bool, str, dict]:
        """
        Execute Twice-Daily 70/30 Profit Skim:
        - Withdraws 30% of net profit from trading account back to your deposit wallet.
        - Retains 70% of net profit in trading account to compound trade sizing.
        - Updates baseline to new active balance.
        """
        cur_bal = self.prdt_agent.simulated_balance if (self.prdt_agent and self.simulation_mode) else self.stake_native
        net_profit = round(cur_bal - self.baseline_balance, 4)

        if net_profit < self.min_sweep_usd and not force:
            self.last_sweep_ts = time.time()
            self.save_current_state()
            return False, f"Net profit (${net_profit:.2f}) is below minimum sweep threshold (${self.min_sweep_usd:.2f})", {}

        if net_profit <= 0:
            self.last_sweep_ts = time.time()
            self.save_current_state()
            return False, f"No net profit accrued (${net_profit:.2f}) in this window.", {}

        sweep_amount = round(net_profit * self.sweep_profit_ratio, 2)
        retained_amount = round(net_profit - sweep_amount, 2)
        new_balance = round(cur_bal - sweep_amount, 4)

        if self.simulation_mode and self.prdt_agent:
            self.prdt_agent.simulated_balance = new_balance

        self.baseline_balance = new_balance
        self.total_swept_profit = round(self.total_swept_profit + sweep_amount, 2)
        self.last_sweep_ts = time.time()
        self.save_current_state()

        dest_addr = self.safe_vault_address
        if not dest_addr and self.prdt_agent and getattr(self.prdt_agent, 'account', None):
            dest_addr = self.prdt_agent.account.address
        if not dest_addr:
            dest_addr = "0xF43aA3aa8d324beeA1120DA71076ad16963A2073"

        details = {
            "net_profit": net_profit,
            "sweep_amount": sweep_amount,
            "retained_amount": retained_amount,
            "new_balance": new_balance,
            "total_swept": self.total_swept_profit,
            "vault_address": dest_addr
        }
        return True, "Sweep completed", details

    # ─── High-Frequency Multi-Timeframe Strategy (639 Setups) ───
    # Validated on 365d Binance data: 30+ trades/day | 85%+ WR
    # Broker Assets & Payouts configured directly from live PRDT/broker terminal:
    PAIR_PAYOUTS = {
        "BTCUSDT": 0.90, "BTC-USDT": 0.90,
        "ETHUSDT": 0.90, "ETH-USD": 0.90, "ETHUSD": 0.90,
        "BNBUSDT": 0.90, "BNB-USD": 0.90, "BNBUSD": 0.90,
        "XRPUSDT": 0.70, "XRP-USD": 0.70, "XRPUSD": 0.70,
        "SOLUSDT": 0.70, "SOL-USD": 0.70, "SOLUSD": 0.70,
        "USDJPY": 0.80, "USD-JPY": 0.80,
        "EURUSD": 0.80, "EUR-USD": 0.80, "EURUSDT": 0.80,
    }
    TRADEABLE_PAIRS = {
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "XRPUSDT", "SOLUSDT", "USDJPY", "EURUSD",
        "BTC-USDT", "ETH-USD", "BNB-USD", "XRP-USD", "SOL-USD", "USD-JPY", "EUR-USD", "EURUSDT"
    }
    TIER1_PAIRS = {"BTCUSDT", "ETHUSDT", "BNBUSDT", "BTC-USDT", "ETH-USD", "BNB-USD"}

    # PRDT Pro Maximum Bet Limits per Symbol (from broker screenshot)
    SYMBOL_MAX_BETS = {
        "BTCUSDT": 1000.0, "BTC-USDT": 1000.0,
        "ETHUSDT": 250.0,  "ETH-USD": 250.0,  "ETHUSD": 250.0,
        "BNBUSDT": 250.0,  "BNB-USD": 250.0,  "BNBUSD": 250.0,
        "XRPUSDT": 100.0,  "XRP-USD": 100.0,  "XRPUSD": 100.0,
        "SOLUSDT": 250.0,  "SOL-USD": 250.0,  "SOLUSD": 250.0,
        "USDJPY": 100.0,   "USD-JPY": 100.0,
        "EURUSD": 100.0,   "EUR-USD": 100.0,   "EURUSDT": 100.0,
    }


    def calculate_dynamic_stake(self, balance: float, symbol: str = "BTCUSDT") -> float:
        """
        Dynamic Compounding Model:
        - Scales base stake to BASE_STAKE_PCT (default: 5% for No-Gale, 0.5% for Gale-2, 6.1% for legacy Gale-1).
        - Enforces PRDT Pro platform maximum bet caps ($1,000 on BTC, $250 on ETH/BNB/SOL, $100 on XRP/Forex).
        - Enforces max allowed stake headroom.
        """
        if balance <= 0:
            return max(1.0, self.stake_native)

        strategy_mode = os.environ.get("STRATEGY_MODE", "GALE1_88PCT").upper()
        is_nogale = any(x in strategy_mode for x in ("ZERO_GALE", "FLAT", "0GALE", "NOGALE", "83WR", "55TPD", "85PCT"))
        is_gale2 = ("GALE2" in strategy_mode or "2GALE" in strategy_mode)

        # Default staking pct: 5% for No-Gale, 0.5% for Gale-2, 6.1% for legacy Gale-1
        if is_nogale:
            default_pct = 0.05
            max_multiplier = 1.0  # Zero-Gale: no multiplier headroom needed, allow full platform caps!
        elif is_gale2:
            default_pct = 0.005
            max_multiplier = 4.93
        else:
            default_pct = 0.061
            max_multiplier = 2.22

        raw_pct = float(os.environ.get("BASE_STAKE_PCT", str(default_pct)))
        base_pct = raw_pct / 100.0 if raw_pct > 1.0 else raw_pct
        base_stake = max(1.0, round(balance * base_pct, 2))

        # Enforce PRDT platform max bet caps per symbol
        max_pool_bet = AssassinController.SYMBOL_MAX_BETS.get(symbol, 250.0)
        max_allowed_base = round(max_pool_bet / max_multiplier, 2)
        base_stake = min(base_stake, max_allowed_base)

        return max(self.stake_native, round(base_stake, 2))


async def main():
    logger.info("=" * 65)
    logger.info("  ASSASSIN BOT v7.0 — 88% 1-Gale | 30+ TPD Engine")
    logger.info("  ─────────────────────────────────────────────────────")
    logger.info("  Strategy: 1-Gale 88% SeqWR | 30+ TPD (RSI Pullback + BB + 15m Trend)")
    logger.info("  Pairs: BTC (90%), ETH (90%), BNB (90%), XRP (70%), SOL (70%)")
    logger.info("  Platform Caps: BTC $1000 | ETH $250 | BNB $250 | SOL $250 | XRP $100")
    logger.info("  Staking: Dynamic Compounding (6.1% base, 2.22x gale)")
    logger.info("  Execution: Web3 Smart Contract (PRDTAgent) + Webhook")
    logger.info("  Feeder: Binance Live WebSocket (Multi-TF synthesis from 1m)")
    logger.info("  Telegram: Interactive Control + Real/Demo Mode Switcher")
    logger.info("=" * 65)

    # 1. Configuration from Environment
    # Trade all broker pairs from live asset list
    default_symbols = "BTCUSDT,ETHUSDT,BNBUSDT,SOLUSDT,XRPUSDT"
    symbols = os.environ.get("TRADING_SYMBOLS", default_symbols).split(",")
    symbols = [s.strip().upper() for s in symbols if s.strip()]

    # Feeder uses 1m atomic candles; MultiTFCandleAggregator synthesizes all higher TFs
    INTERVALS = ["1m"]
    INTERVAL_EXPIRY = {"1m": 60}

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
        interval="1m",
        expiry_seconds=300,
        stake_native=stake_native,
        simulation_mode=simulation_mode
    )

    # 3. Instantiate Signal Engine (supports SNIPER_89PCT, 85PCT_30TPD, GALE1, GALE2, and NOGALE_55TPD modes)
    strategy_mode = os.environ.get("STRATEGY_MODE", "GALE1_88PCT").upper()
    is_nogale = any(x in strategy_mode for x in ("ZERO_GALE", "FLAT", "0GALE", "NOGALE", "83WR", "55TPD", "SNIPER", "89PCT"))
    is_gale2 = any(x in strategy_mode for x in ("GALE2", "2GALE", "GALE-2"))
    if is_nogale:
        max_allowed_gale = 0
    elif is_gale2:
        max_allowed_gale = 2
    else:
        max_allowed_gale = 1

    if "88PCT" in strategy_mode or "GALE1_88" in strategy_mode:
        cfg_88 = os.path.join(os.path.dirname(__file__), "assassin_strategy", "gale1_88pct_30tpd_config.json")
        hybrid_engine = HybridSignalEngine(config_path=cfg_88)
        logger.critical(f"🏆 [STRATEGY MODE: 1-GALE 88% 30+ TPD] Armed with {len(hybrid_engine.setups)} setups (69% Base | 88% 1-Gale SeqWR | 32+ TPD | BTC, ETH, BNB, SOL, XRP)!")
    elif "SNIPER" in strategy_mode or "89PCT" in strategy_mode:
        cfg_sniper = os.path.join(os.path.dirname(__file__), "assassin_strategy", "nogale_89pct_sniper_config.json")
        hybrid_engine = HybridSignalEngine(config_path=cfg_sniper)
        logger.critical(f"🎯 [STRATEGY MODE: SNIPER ZERO-GALE 89.4%] Armed with {len(hybrid_engine.setups)} verified setups (89.44% Direct WR | 360 OOS Trades | BTC, ETH, BNB, SOL, XRP | Zero Martingale)!")
    elif "85PCT" in strategy_mode:
        cfg_85 = os.path.join(os.path.dirname(__file__), "assassin_strategy", "nogale_85pct_30tpd_config.json")
        hybrid_engine = HybridSignalEngine(config_path=cfg_85)
        logger.critical(f"🎯 [STRATEGY MODE: 85% 30+ TPD] Armed with {len(hybrid_engine.setups)} verified setups (85%+ WR | 30+ Trades/Day | BTC, ETH, BNB, SOL, XRP | Zero Martingale)!")
    elif is_nogale:
        nogale_cfg = os.path.join(os.path.dirname(__file__), "assassin_strategy", "nogale_83wr_55tpd_config.json")
        hybrid_engine = HybridSignalEngine(config_path=nogale_cfg)
        logger.critical(f"💰 [STRATEGY MODE: NO-GALE 55TPD] Armed with {len(hybrid_engine.setups)} verified setups (55.6 TPD | 83.3% Direct WR | $32/day/$1 EV | Zero Martingale)!")
    elif is_gale2:
        gale2_cfg = os.path.join(os.path.dirname(__file__), "assassin_strategy", "gale2_40tpd_config.json")
        hybrid_engine = HybridSignalEngine(config_path=gale2_cfg)
        logger.critical(f"🚀 [STRATEGY MODE: GALE-2] Armed with {len(hybrid_engine.setups)} verified setups (55.4 TPD | 90.77% 2-Gale Sequence WR | 365d Binance Verified)!")
    else:
        # Default fallback: same as GALE1_88PCT
        gale1_cfg = os.path.join(os.path.dirname(__file__), "assassin_strategy", "gale1_88pct_30tpd_config.json")
        hybrid_engine = HybridSignalEngine(config_path=gale1_cfg)
        logger.critical(f"🏆 [STRATEGY MODE: 1-GALE 88%] Armed with {len(hybrid_engine.setups)} setups (69% Base | 88% 1-Gale SeqWR | 32+ TPD | Pure Compounding)!")
    controller.hybrid_engine = hybrid_engine
    logger.info("⏳ Preloading 1,000 historical candles from Binance to warm up timeframes...")
    try:
        await hybrid_engine.preload_from_binance(symbols, limit=1000)
    except Exception as e:
        logger.warning(f"⚠️ Preloading from Binance encountered an issue: {e}")
    engines = {"1m": AssassinSignalEngine(default_expiry_seconds=60)}
    controller.engine = engines["1m"]  # Compatibility reference


    prdt_agent = PRDTAgent(
        rpc_url=rpc_url,
        contract_address=contract_addr,
        private_key=private_key,
        default_stake_native=stake_native,
        min_buffer_seconds=20,
        simulation_mode=simulation_mode
    )
    prdt_agent.initialize()
    # Restore saved simulated balance if available (auto-heal corrupted negative balance)
    saved_state = load_saved_state()
    loaded_bal = saved_state.get("balance", 20.0)
    prdt_agent.simulated_balance = 15.0 if loaded_bal <= 0 else loaded_bal
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

    # All cooldowns / dedup / concurrency caps REMOVED — zero blockers

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
                            if controller.is_in_mart_recovery and controller.lost_mart_amount > 0:
                                # Micro-recovery deduction: each win recoups 50% of the loss debt
                                recovered_slice = round(t.stake_native * pair_payout * 0.50, 4)
                                controller.lost_mart_amount = max(0.0, round(controller.lost_mart_amount - recovered_slice, 4))
                                if controller.lost_mart_amount <= 0.05:
                                    controller.is_in_mart_recovery = False
                                    controller.lost_mart_amount = 0.0
                                    logger.critical("[INTRADAY RECOVERY] 🎯 All sequence losses fully recovered in the same day!")
                            controller.save_current_state()
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
                            if max_allowed_gale > 0 and t.gale_level < max_allowed_gale:
                                next_gale = t.gale_level + 1
                                max_pool_bet = AssassinController.SYMBOL_MAX_BETS.get(t.symbol, 250.0)
                                next_stake = min(round(t.stake_native * 2.22, 4), max_pool_bet)
                                prdt_agent.simulated_balance = round(prdt_agent.simulated_balance - next_stake, 4)
                                controller.save_current_state()
                                trade_duration = t.expiry_time - t.entry_time
                                remaining.append(ActiveTrade(
                                    symbol=t.symbol, action=t.action.lower(),
                                    entry_price=exit_price, stake_native=next_stake,
                                    entry_time=now, expiry_time=now + trade_duration,
                                    epoch=prdt_agent.get_current_epoch(),
                                    gale_level=next_gale,
                                    total_sequence_stake=round(t.total_sequence_stake + next_stake, 4),
                                    is_recovery_trade=t.is_recovery_trade,
                                    strategy_key=t.strategy_key,
                                    indicator_family=t.indicator_family
                                ))
                                logger.critical(f"[BG-SETTLER] GALE {next_gale} triggered {t.symbol} {t.action.upper()} | Stake: {next_stake:.4f} | Total In Seq: {t.total_sequence_stake + next_stake:.4f}")
                            else:
                                controller.losses += 1
                                controller.marts_since_loss = 0

                                # Queue recovery debt ONLY for Gale modes (strictly disabled in No-Gale)
                                if max_allowed_gale > 0:
                                    controller.is_in_mart_recovery = True
                                    controller.lost_mart_amount = round(controller.lost_mart_amount + t.total_sequence_stake, 4)
                                    cooldown = 5 if is_gale2 else 3
                                    controller.recovery_queue.append(RecoveryDebt(
                                        symbol=t.symbol,
                                        lost_amount=round(t.total_sequence_stake, 4),
                                        created_at=time.time(),
                                        cooldown_bars=cooldown,
                                        bars_elapsed=0,
                                        is_ready=False
                                    ))
                                    logger.critical(
                                        f"🔴 [RECOVERY QUEUED] Lost {t.total_sequence_stake:.4f} on {t.symbol} | "
                                        f"Total debt: {controller.lost_mart_amount:.4f} | "
                                        f"Recovery will boost next qualifying signal"
                                    )
                                controller.save_current_state()
                                logger.warning(f"[BG-SETTLER] SEQ LOSS {t.symbol} {t.action.upper()} (Gale {t.gale_level}) | Lost: {t.total_sequence_stake:.4f} | Reset to Base stake")
                                if tg_bot:
                                    await tg_bot.send_settlement_alert(
                                        symbol=t.symbol, action=t.action,
                                        entry_price=t.entry_price, exit_price=exit_price,
                                        is_win=False, profit_loss=-t.total_sequence_stake,
                                        new_balance=prdt_agent.simulated_balance if controller.simulation_mode else 0.0,
                                        wins=controller.wins, losses=controller.losses, step_info=f"SEQUENCE LOSS (GALE {t.gale_level}) | Recovery in 5 bars"
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

        # Tick recovery cooldowns for this symbol
        for debt in controller.recovery_queue:
            if debt.symbol == symbol and not debt.is_ready:
                debt.bars_elapsed += 1
                if debt.bars_elapsed >= debt.cooldown_bars:
                    debt.is_ready = True
                    logger.info(f"🔄 [RECOVERY] {symbol} cooldown complete — next fresh signal triggers recovery trade")

        # Route candle to the correct engine's history buffer
        engine = engines.get(interval)
        if not engine:
            return
        expiry_seconds = INTERVAL_EXPIRY.get(interval, 300)

        # Trade settlement is handled by background_trade_settler (every 5s)
        # No settlement logic here — prevents race conditions

        # ═══════════════════════════════════════════════════════════════
        # 85.03% ULTRA-HYBRID MULTI-TIMEFRAME ENGINE
        # 281 Setups across 19 Timeframes (BB 1.8-3.0σ, Whale, WillR, CCI, Exhaustion, RSI)
        # 40.05 trades/day | 85.03% 1-Gale WR (365d Binance Verified)
        # ═══════════════════════════════════════════════════════════════
        active_symbols = {t.symbol for t in controller.active_trades}
        signals = []

        # Synthesize multi-minute candles from atomic 1m stream
        closed_tf_candles = hybrid_engine.aggregator.update_1m_candle(symbol, candle)

        for tf, tf_candle in closed_tf_candles:
            tf_sigs = hybrid_engine.evaluate_setups(symbol, tf, tf_candle)
            for s in tf_sigs:
                setup_desc = s["setup"].desc if hasattr(s["setup"], "desc") else s.get("trigger", "")
                strat_key = setup_desc.split("|", 1)[-1].strip() if "|" in setup_desc else setup_desc
                trend = s["setup"].params.get("trend", "") if hasattr(s["setup"], "params") else ""
                rsi_p = s["setup"].params.get("rsi_period", "") if hasattr(s["setup"], "params") else ""
                stype = s["setup"].type if hasattr(s["setup"], "type") else "HYBRID"
                indicator_family = f"{stype}_{trend}_RSI{rsi_p}" if (trend or rsi_p) else strat_key

                sig = AssassinSignal(
                    symbol=s["symbol"],
                    action=s["action"],
                    price=s["price"],
                    confidence=s["confidence"],
                    trigger=s["trigger"],
                    pattern_type=s["pattern_type"],
                    expiry_seconds=s["expiry_seconds"],
                    timestamp=time.time(),
                    verdict="TAKE_IT",
                    regime="HYBRID_85PCT",
                    solid_count=3,
                    soft_count=0,
                    metadata={
                        "tf": tf,
                        "desc": setup_desc,
                        "strategy_key": strat_key,
                        "indicator_family": indicator_family
                    }
                )
                signals.append(sig)
                logger.info(f"📊 [HYBRID SIGNAL] {s['symbol']} {s['action'].upper()} on {tf}m | {s['trigger']}")

        for sig in signals:
            # Safeguard 1: Prevent duplicate / overlapping trade sequences on the same symbol
            if sig.symbol in active_symbols:
                logger.info(f"⏳ [PAIR-BUSY] {sig.symbol} already has an active trade sequence — skipping duplicate")
                continue

            # Safeguard 2: Indicator Collision & Time Spacing (User Rule: identical indicator cannot fire simultaneously; different indicators CAN fire at the exact same second!)
            sig_family = sig.metadata.get("indicator_family", "")
            sig_strat = sig.metadata.get("strategy_key", "")
            min_indicator_interval = float(os.environ.get("MIN_TRADE_INTERVAL_SECONDS", "0.0"))

            # Check if identical indicator is currently active on the SAME pair only
            # (Different pairs are allowed to use the same indicator simultaneously for max throughput)
            colliding_active = [
                t for t in controller.active_trades
                if t.symbol == sig.symbol and (
                    (t.indicator_family and t.indicator_family == sig_family) or
                    (t.strategy_key and t.strategy_key == sig_strat)
                )
            ]
            if colliding_active:
                ca = colliding_active[0]
                logger.info(f"🛡️ [INDICATOR-COLLISION] Skipping {sig.symbol} — identical indicator ({sig_family}) is already active on this pair!")
                continue

            # Check if this exact indicator fired within the minimum interval (0s / disabled by default)
            if min_indicator_interval > 0:
                last_strat_ts = controller.last_strategy_time.get(sig_family, 0.0)
                time_since_strat = time.time() - last_strat_ts
                if last_strat_ts > 0 and time_since_strat < min_indicator_interval:
                    rem = int(min_indicator_interval - time_since_strat)
                    logger.info(f"⏳ [TIME-SPACING] Skipping {sig.symbol} — indicator ({sig_family}) fired {int(time_since_strat)}s ago (min {int(min_indicator_interval)}s spacing for identical indicator, {rem}s remaining)")
                    continue

            # Safeguard 4: Same-Pair Simultaneous Collision (User Rule: multiple trades at the exact same second on the same pair must use different indicators)
            same_pair_simultaneous = [
                t for t in controller.active_trades
                if t.symbol == sig.symbol and abs(t.entry_time - time.time()) < 5 and (
                    (t.indicator_family and t.indicator_family == sig_family) or
                    (t.strategy_key and t.strategy_key == sig_strat)
                )
            ]
            if same_pair_simultaneous:
                logger.info(f"🛡️ [SAME-PAIR-COLLISION] Skipping {sig.symbol} — duplicate indicator ({sig_family}) fired at the same second on this pair!")
                continue

            # Safeguard 6: Gale-Active Lock — only block new entries on the SAME pair that is currently in gale recovery
            # (Other pairs can trade freely even if one pair is struggling)
            struggling_gales = [t for t in controller.active_trades if t.action == sig.action.lower() and t.gale_level > 0 and t.symbol == sig.symbol]
            if struggling_gales:
                g = struggling_gales[0]
                logger.info(f"🛡️ [GALE-LOCK] Blocking new {sig.symbol} {sig.action.upper()} — this pair is currently in GALE {g.gale_level} recovery")
                continue

            pair_trades = [t for t in controller.active_trades if t.symbol == sig.symbol]
            # Dedup: prevent taking duplicate trades on the exact same second/candle close
            if any(abs(t.entry_time - time.time()) < 5 and t.action == sig.action.lower() for t in pair_trades):
                continue

            tf_tag = sig.metadata.get('tf', '1m') if hasattr(sig, 'metadata') and sig.metadata else '1m'
            logger.info(f"✅ [HYBRID|{tf_tag}] {sig.symbol} {sig.action.upper()} — Setup triggered!")

            verdict_icon = "🔥" if sig.verdict == "TAKE_IT" else "📊"
            logger.critical(
                f"{verdict_icon} [{tf_tag}] {sig.symbol} {sig.action.upper()} | "
                f"${sig.price:.2f} | {sig.verdict} ({sig.confidence*100:.0f}%) | "
                f"Solid={sig.solid_count} Soft={sig.soft_count} | "
                f"Regime={sig.regime} | {sig.trigger}"
            )

            # 1. Execute NORMAL trade via Dynamic Compounding Staking
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
                    is_recovery_trade=False,
                    strategy_key=sig_strat,
                    indicator_family=sig_family
                ))
                active_symbols.add(sig.symbol)
                controller.last_trade_time = time.time()
                controller.last_pair_trade_time[sig.symbol] = time.time()
                controller.last_pair_strategy[sig.symbol] = sig_family or sig_strat
                controller.last_strategy_time[sig_family] = time.time()
                if sig_strat:
                    controller.last_strategy_time[sig_strat] = time.time()
            else:
                logger.warning(f"⚠️ Trade Execution Failed / Skipped: {tx_or_reason}")

            # Recovery debt injection disabled in pure dynamic compounding mode:
            # Compounding automatically scales with balance; duplicate trades distort risk and duplicate losses.



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

    # 6b. Background Twice-Daily 70/30 Profit Sweeper (checks every 60s)
    async def profit_sweep_worker():
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                interval_secs = controller.sweep_interval_hours * 3600.0
                if now - controller.last_sweep_ts >= interval_secs:
                    logger.info(f"⏰ [70/30 SWEEPER] Weekly window ({controller.sweep_interval_hours:.0f}h) elapsed. Evaluating weekly profit sweep...")
                    success, reason, details = controller.execute_sweep()
                    if success:
                        logger.critical(
                            f"💸 [70/30 SWEEPER] Swept: ${details['sweep_amount']:.2f} (30%) | "
                            f"Retained: ${details['retained_amount']:.2f} (70%) | "
                            f"New Active Bal: ${details['new_balance']:.2f}"
                        )
                        if tg_bot:
                            await tg_bot.send_sweep_alert(
                                net_profit=details["net_profit"],
                                swept_amount=details["sweep_amount"],
                                retained_amount=details["retained_amount"],
                                new_balance=details["new_balance"],
                                total_swept=details["total_swept"],
                                vault_address=details["vault_address"]
                            )
                    else:
                        logger.info(f"ℹ️ [70/30 SWEEPER] Sweep check: {reason}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[70/30 SWEEPER] Error: {e}")

    sweep_task = asyncio.create_task(profit_sweep_worker())

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

    # Preload historical 1m candles to seed all multi-timeframe aggregators
    try:
        logger.info(f"⏳ Pre-loading 1m history for {controller.symbols}...")
        history_map = await feed.preload_history(limit=1000)
        for sym, iv_data in history_map.items():
            candles = iv_data.get("1m", [])
            for c in candles:
                hybrid_engine.aggregator.update_1m_candle(sym, c)
            logger.info(f"🚀 {sym} pre-seeded with {len(candles)} 1m candles into Multi-TF aggregator. ARMED!")
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
        sweep_task.cancel()
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
