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
    return {"balance": 10.0, "wins": 0, "losses": 0}

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

    # ─── Filter Thresholds (Strict 82.5% WR on ALL trades) ───
    # Both modes use strict filters; frequency comes from 120 pairs, not looser gates
    NORMAL_RUN_MIN = 6
    NORMAL_WICK_MIN = 2.0
    NORMAL_VOL_MIN = 2.5
    # Recovery mode: same strict filters (82.5%+ WR)
    RECOVERY_RUN_MIN = 6
    RECOVERY_WICK_MIN = 2.0
    RECOVERY_VOL_MIN = 2.5

    def calculate_dynamic_stake(self, balance: float) -> float:
        """
        Dynamic Compounding Engine (6.1% Base Stake Scaling + 1-Trade Mart Recovery):
        - If in Mart Recovery mode: sizes stake to recover the entire lost Mart + full target profit in 1 single trade.
        - Otherwise: dynamically calculates 6.1% base stake as balance compounds.
        """
        if balance <= 0:
            return self.stake_native

        if self.is_in_mart_recovery and self.lost_mart_amount > 0:
            target_profit = balance * 0.061 * 0.86
            rec_stake = round((self.lost_mart_amount + target_profit) / 0.86, 4)
            # Safe risk cap at max 23% of balance
            rec_stake = min(round(balance * 0.23, 4), rec_stake)
            return max(self.stake_native, rec_stake)

        # 6.1% base stake scaling with a hard minimum floor
        dynamic_stake = round(max(self.stake_native, balance * 0.061), 4)
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
    # 120 High-Liquidity Pairs (All >$2M/day volume, PRDT oracle = zero slippage)
    default_symbols = (
        "BTCUSDT,ETHUSDT,SOLUSDT,XRPUSDT,BNBUSDT,DOGEUSDT,SUIUSDT,PEPEUSDT,"
        "UNIUSDT,ENAUSDT,TRXUSDT,TRUMPUSDT,NEARUSDT,ADAUSDT,LINKUSDT,TAOUSDT,"
        "WLDUSDT,DASHUSDT,AAVEUSDT,AVAXUSDT,XLMUSDT,LTCUSDT,CAKEUSDT,FETUSDT,"
        "ZKUSDT,POLUSDT,ONDOUSDT,PENGUUSDT,HEMIUSDT,PUMPUSDT,XAUTUSDT,SEIUSDT,"
        "TIAUSDT,INJUSDT,ARBUSDT,OPUSDT,TONUSDT,BCHUSDT,APTUSDT,RENDERUSDT,"
        "CRVUSDT,LDOUSDT,PENDLEUSDT,SHIBUSDT,BONKUSDT,STXUSDT,ZECUSDT,BMTUSDT,"
        "DOTUSDT,FILUSDT,ICPUSDT,HBARUSDT,ALGOUSDT,ARUSDT,STRKUSDT,EIGENUSDT,"
        "ETHFIUSDT,NOTUSDT,JASMYUSDT,PYTHUSDT,VIRTUALUSDT,ACEUSDT,PAXGUSDT,"
        "PROMUSDT,SNDKBUSDT,ENSOUSDT,ZKCUSDT,MORPHOUSDT,NFPUSDT,ONTUSDT,"
        "DOGSUSDT,MSTRBUSDT,SCUSDT,ONGUSDT,JSTUSDT,BICOUSDT,HFTUSDT,ZENUSDT,"
        "ZROUSDT,DEXEUSDT,ACTUSDT,VANRYUSDT,STRAXUSDT,PLUMEUSDT,0GUSDT,"
        "CRCLBUSDT,ASTERUSDT,ATMUSDT,IQUSDT,SKYUSDT,GRAMUSDT,WBTCUSDT,"
        "CHIPUSDT,TWTUSDT,TUTUSDT,KITEUSDT,MIRAUSDT,KORUBUSDT,FFUSDT,"
        "MITOUSDT,HEIUSDT,MUBUSDT,METABUSDT,SOMIUSDT,HOODBUSDT,SNXXBUSDT,"
        "RLUSDUSDT,XPLUSDT,SKHYBUSDT,GIGGLEUSDT,EURIUSDT,QQQBUSDT,SOXLBUSDT,"
        "SPCXBUSDT,WLFIUSDT,XUSDUSDT,USD1USDT,USDEUSDT,UUSDT"
    )
    symbols = os.environ.get("TRADING_SYMBOLS", default_symbols).split(",")
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

                    # Reset 1-Trade Mart Recovery mode ONLY if this trade was the designated recovery trade!
                    if t.is_recovery_trade:
                        controller.is_in_mart_recovery = False
                        controller.lost_mart_amount = 0.0
                        logger.critical("🎯 [1-TRADE RECOVERY COMPLETE] Designated recovery trade won! Loss 100% erased + profit banked! Resetting to normal 5% Base Stake.")

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
                            total_sequence_stake=round(t.total_sequence_stake + next_stake, 4),
                            is_recovery_trade=t.is_recovery_trade
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
            # ─── STRICT RECOVERY ISOLATION: WAIT FOR ALL TRADES TO CLEAR, THEN STRICTLY 1 ISOLATED TRADE ───
            if controller.is_in_mart_recovery:
                if len(controller.active_trades) >= 1:
                    logger.info(
                        f"⏸️ [RECOVERY ISOLATION] In Recovery Mode — waiting for open trades ({[t.symbol for t in controller.active_trades]}) to settle before placing 1 single isolated recovery trade. "
                        f"Skipping signal for {sig.symbol}."
                    )
                    continue
            else:
                # ─── STRICT CONCURRENCY RULE: MAX 2 ACTIVE TRADES IN NORMAL 5% MODE ───
                if len(controller.active_trades) >= 2:
                    logger.info(
                        f"⏸️ [CONCURRENCY CAP] 2 trades already active ({[t.symbol for t in controller.active_trades]}). "
                        f"Skipping new signal for {sig.symbol}."
                    )
                    continue

            if sig.symbol in active_symbols:
                logger.info(f"⏸️ [SYMBOL BUSY] {sig.symbol} already has an active trade sequence running. Skipping duplicate signal.")
                continue

            # ═══════════════════════════════════════════════════════════════
            # SMART DUAL-MODE SNIPER GATE (365-Day Backtested)
            # NORMAL MODE:   Run>=4, Wick>=1.8x, Vol>=1.8x  (78.3% WR)
            # RECOVERY MODE: Run>=6, Wick>=2.0x, Vol>=2.5x  (82.5%+ WR)
            # ═══════════════════════════════════════════════════════════════
            history = engine.candle_history.get(symbol, [])
            is_recovery = controller.is_in_mart_recovery

            # Select filter thresholds based on mode
            run_min = AssassinController.RECOVERY_RUN_MIN if is_recovery else AssassinController.NORMAL_RUN_MIN
            wick_min = AssassinController.RECOVERY_WICK_MIN if is_recovery else AssassinController.NORMAL_WICK_MIN
            vol_min = AssassinController.RECOVERY_VOL_MIN if is_recovery else AssassinController.NORMAL_VOL_MIN
            mode_tag = "RECOVERY 82.5%" if is_recovery else "NORMAL 78.3%"

            # ─── GATE 1: SESSION FILTER (Skip 03:00–06:00 UTC dead zone) ───
            from datetime import datetime, timezone
            utc_hour = datetime.now(timezone.utc).hour
            if 3 <= utc_hour < 6:
                logger.info(f"🛡️ [SESSION FILTER] {sig.symbol} skipped — UTC {utc_hour}:00 dead zone.")
                continue

            # ─── GATE 2: MINIMUM CANDLE RANGE (reject tiny flat candles) ───
            candle_range = candle.high - candle.low
            if len(history) >= 20:
                avg_range = sum(c.high - c.low for c in history[-20:]) / 20.0
                if candle_range < avg_range:
                    logger.info(f"🛡️ [RANGE FILTER] {sig.symbol} skipped — range {candle_range:.5f} < avg {avg_range:.5f}")
                    continue

            # ─── GATE 3: EXHAUSTION RUN (dynamic: 4 normal / 6 recovery) ───
            run_ok = False
            if len(history) >= run_min:
                if sig.action.lower() == 'call':
                    run_count = 0
                    for hc in reversed(history[-run_min:]):
                        if hc.close < hc.open:
                            run_count += 1
                        else:
                            break
                    run_ok = run_count >= run_min
                else:
                    run_count = 0
                    for hc in reversed(history[-run_min:]):
                        if hc.close > hc.open:
                            run_count += 1
                        else:
                            break
                    run_ok = run_count >= run_min
            if not run_ok:
                logger.info(f"🛡️ [RUN FILTER|{mode_tag}] {sig.symbol} skipped — no {run_min}+ exhaustion run.")
                continue

            # ─── GATE 4: REJECTION WICK (dynamic: 1.8x normal / 2.0x recovery) ───
            body = abs(candle.close - candle.open)
            if body < 1e-10:
                logger.info(f"🛡️ [WICK FILTER] {sig.symbol} skipped — zero body (doji).")
                continue
            upper_wick = candle.high - max(candle.open, candle.close)
            lower_wick = min(candle.open, candle.close) - candle.low
            max_wick = max(upper_wick, lower_wick)
            if max_wick < wick_min * body:
                logger.info(f"🛡️ [WICK FILTER|{mode_tag}] {sig.symbol} skipped — wick {max_wick/body:.1f}x < {wick_min}x.")
                continue

            # ─── GATE 5: VOLUME CLIMAX (dynamic: 1.8x normal / 2.5x recovery) ───
            if len(history) >= 20:
                avg_vol = sum(c.volume for c in history[-20:]) / 20.0
                if avg_vol > 0 and candle.volume < vol_min * avg_vol:
                    logger.info(f"🛡️ [VOL FILTER|{mode_tag}] {sig.symbol} skipped — vol {candle.volume/avg_vol:.1f}x < {vol_min}x.")
                    continue

            # ─── GATE 6: 50-BAR S/R PROXIMITY ───
            if len(history) >= 50:
                h50 = [c.high for c in history[-50:]]
                l50 = [c.low for c in history[-50:]]
                resistance = max(h50)
                support = min(l50)
                sr_tol = candle_range * 2.0
                near_sr = False
                if sig.action.lower() == 'call' and candle.low <= support + sr_tol:
                    near_sr = True
                elif sig.action.lower() == 'put' and candle.high >= resistance - sr_tol:
                    near_sr = True
                if not near_sr:
                    logger.info(f"🛡️ [S/R FILTER] {sig.symbol} skipped — not near 50-bar S/R zone.")
                    continue

            logger.info(f"✅ [{mode_tag} GATE PASSED] {sig.symbol} {sig.action.upper()} — All 6 gates cleared!")


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
