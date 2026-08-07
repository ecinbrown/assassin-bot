import asyncio
import numpy as np
import time
import csv
import os
import logging
import secrets
import math
from database import insert_tick

logger = logging.getLogger(__name__)

class CSPRNGEngine:
    """
    Cryptographically Secure Pseudo-Random Number Generator (CSPRNG) Engine
    Provides:
    1. OS-level Cryptographic Randomness (secrets.SystemRandom).
    2. Shannon Entropy calculation over rolling tick velocity streams.
    3. Cryptographic order execution jitter to obfuscate automated bot timing.
    """
    def __init__(self):
        self.sys_random = secrets.SystemRandom()

    def calc_shannon_entropy(self, velocities: list) -> float:
        if len(velocities) < 10:
            return 0.5
        events = [1 if v > 0 else (-1 if v < 0 else 0) for v in velocities]
        total = len(events)
        counts = {}
        for ev in events:
            counts[ev] = counts.get(ev, 0) + 1
        entropy = 0.0
        for ev, count in counts.items():
            p = count / total
            if p > 0:
                entropy -= p * math.log2(p)
        max_entropy = math.log2(3)
        return float(entropy / max_entropy)

    async def apply_jitter(self, min_ms: float = 0.05, max_ms: float = 0.18) -> float:
        """Inject cryptographically random delay to obfuscate execution timing from broker engines."""
        delay = self.sys_random.uniform(min_ms, max_ms)
        await asyncio.sleep(delay)
        return delay

# Tick logger - appends every tick to CSV for analysis
TICK_LOG_PATH = os.path.join(os.path.dirname(__file__), "tick_log.csv")
_need_header = not os.path.exists(TICK_LOG_PATH) or os.path.getsize(TICK_LOG_PATH) == 0
_tick_file = open(TICK_LOG_PATH, "a", newline="")
_tick_writer = csv.writer(_tick_file)
if _need_header:
    _tick_writer.writerow(["timestamp", "symbol", "price", "velocity"])
    _tick_file.flush()

class LogicEngine:
    def __init__(self, target_symbols: list = None, notifier=None):
        self.target_symbols = target_symbols if target_symbols else []
        self.notifier = notifier
        self.paused = False
        self.last_prices = {}
        
        # CSPRNG Engine Instance
        self.csprng = CSPRNGEngine()
        
        # Tracking arrays by symbol
        self.recent_velocities = {} 
        self.price_history = {}
        
        # Trade cooldown
        self.last_trade_time = {}
        self.COOLDOWN_SECONDS = 60
        
        # Trade State
        self.active_trade = None # {'action': 'call', 'entry': price, 'target': ts, 'symbol': symbol, 'stake': float}
        self.coordinator = None
        
        # Strategy Mode: 'reversal' (fade) or 'continuation' (trend-follow) — toggles automatically on LOSS
        self.strategy_mode = 'reversal'

    def _evaluate_trades(self, current_time, price, browser_agent=None):
        """Timer Mode Verification: resolves trades exactly at the target timestamp."""
        if self.active_trade and current_time >= self.active_trade['target']:
            action = self.active_trade['action']
            entry = self.active_trade['entry']
            
            win = False
            if action == "call" and price > entry: win = True
            elif action == "put" and price < entry: win = True
            
            # Remove Martingale fallback entirely, pure Flat Stake
            if win:
                logger.info(f"💰 LIVE WIN! Strategic anomaly captured. Maintaining strategy mode: {self.strategy_mode.upper()}")
                if self.coordinator:
                    self.coordinator.report_win()
                if self.notifier:
                    asyncio.create_task(self.notifier.alert_trade_result(
                        self.active_trade.get('symbol', 'ASSET'), action, True, False
                    ))
            else:
                stake_lost = self.active_trade.get('stake', 0.0)
                old_mode = self.strategy_mode
                self.strategy_mode = 'continuation' if self.strategy_mode == 'reversal' else 'reversal'
                logger.warning(f"📉 LIVE LOSS! Switching strategy mode: {old_mode.upper()} ➔ {self.strategy_mode.upper()}")
                if self.coordinator:
                    # In Flat Stake, report_loss just clears the flag, we don't multiply stakes.
                    self.coordinator.report_loss(stake_lost)
                    if hasattr(self.coordinator, 'martingale_armed'):
                        self.coordinator.martingale_armed = False # Ensure no multiplier is used
                if self.notifier:
                    asyncio.create_task(self.notifier.alert_trade_result(
                        self.active_trade.get('symbol', 'ASSET'), action, False, False
                    ))
                
            self.active_trade = None

    async def process_tick_stream(self, tick_queue: asyncio.Queue, browser_agent=None):
        logger.info("Logic Engine: DUAL-CORE 90% ENGINE ONLINE (Straight-Line Snap + Mega Pip Bomb)")
        
        while True:
            tick = await tick_queue.get()
            
            if self.paused:
                continue
                
            symbol = tick.get('symbol')
            if self.target_symbols and symbol not in self.target_symbols:
                continue
                
            price = float(tick.get('price'))
            timestamp = tick.get('timestamp')
            
            # Initialize arrays
            if symbol not in self.last_prices:
                self.last_prices[symbol] = None
                self.recent_velocities[symbol] = []
                self.price_history[symbol] = []
                self.last_trade_time[symbol] = 0
                
            velocity = 0.0
            last_price = self.last_prices[symbol]
            if last_price is not None:
                velocity = price - last_price
            self.last_prices[symbol] = price
            
            # Log tick
            _tick_writer.writerow([timestamp, symbol, price, velocity])
            _tick_file.flush()
            
            # Evaluate outstanding trades
            self._evaluate_trades(time.time(), price, browser_agent)
            
            # Track price history
            self.price_history[symbol].append(price)
            if len(self.price_history[symbol]) > 100:
                self.price_history[symbol].pop(0)
                
            insert_tick(timestamp, symbol, price, abs(velocity))
            
            # Sliding velocity window
            self.recent_velocities[symbol].append(velocity)
            if len(self.recent_velocities[symbol]) > 100:
                self.recent_velocities[symbol].pop(0)
            
            vels = self.recent_velocities[symbol]
            prices = self.price_history[symbol]
            
            # Need enough data for 100-tick window
            if len(vels) < 100 or len(prices) < 100:
                continue
                
            # Prevent fake hallucinations in dead markets
            if abs(velocity) < 0.00010:
                continue

            current_sec = time.time() % 60
            ttb = 60.0 - current_sec
            
            # Calculate Z-Score (100 Window)
            w100 = vels[-100:]
            std_v = np.std(w100)
            if std_v == 0: continue
            z_score = (velocity - np.mean(w100)) / std_v
            
            # PC10 (Price Change 10 ticks in Pips)
            pc10 = abs(price - prices[-11]) / prices[-11] * 10000 if prices[-11] > 0 else 0
            
            # Flips20 (Direction Flips in last 20 ticks)
            flips_20 = 0
            recent_20_vels = vels[-20:]
            for j in range(1, len(recent_20_vels)):
                if (recent_20_vels[j] > 0) != (recent_20_vels[j-1] > 0):
                    flips_20 += 1

            # Log high z-scores for diagnostics (every 60s max)
            if abs(z_score) > 1.5 and (not hasattr(self, '_last_diag') or (time.time() - getattr(self, '_last_diag', 0)) > 60):
                self._last_diag = time.time()
                logger.info(f"📊 [{symbol}] Z={z_score:.2f} | PC10={pc10:.1f}pips | Flips={flips_20} | TTB={ttb:.0f}s")
                    
            action = None
            trigger_name = ""
            
            # Action selection based on active strategy mode (toggles on loss)
            if self.strategy_mode == 'reversal':
                potential_action = "put" if z_score > 0 else "call"
                mode_label = "REVERSAL"
            else:
                potential_action = "call" if z_score > 0 else "put"
                mode_label = "CONTINUATION"
            
            # ═══════════════════════════════════════════════
            # CORE 1: STRAIGHT-LINE SNAP (10 Trades | 90.0% WR)
            # ═══════════════════════════════════════════════
            # A massive volume spike with less than 2 direction flips in the last 20 ticks
            # indicates an unnaturally clean straight-line trend forced by the PRNG.
            if abs(z_score) > 3.5 and flips_20 < 2:
                action = potential_action
                trigger_name = f"CORE 1: STRAIGHT-LINE SNAP [{mode_label}] (Z={z_score:.2f}, Flips={flips_20})"
                
            # ═══════════════════════════════════════════════
            # CORE 2: MEGA PIP BOMB (10 Trades | 90.0% WR)
            # ═══════════════════════════════════════════════
            # A 30+ pip move in 10 ticks occurring with more than 15s left to the buzzer.
            elif abs(z_score) > 2.5 and ttb > 15.0 and pc10 > 30.0:
                action = potential_action
                trigger_name = f"CORE 2: MEGA PIP BOMB [{mode_label}] (Z={z_score:.2f}, PC10={pc10:.1f}pips, TTB={ttb:.0f}s)"

            if action:
                now = time.time()
                elapsed = now - self.last_trade_time.get(symbol, 0)
                
                # Safety: force-clear stuck trades older than 120s
                if self.active_trade and (now - self.active_trade.get('placed_at', now)) > 120:
                    logger.warning(f"⚠️ Force-clearing stuck trade (>120s old)")
                    self.active_trade = None
                
                # Enforce cooldown and single-trade limit
                if elapsed < self.COOLDOWN_SECONDS:
                    logger.debug(f"🕐 Signal blocked by cooldown ({elapsed:.0f}s < {self.COOLDOWN_SECONDS}s)")
                    continue
                if self.active_trade is not None:
                    logger.debug(f"🔒 Signal blocked — active trade pending resolution")
                    continue
                    
                # Exact minute rollover
                target_time = (int(now // 60) + 1) * 60 + 1.0 
                
                logger.critical(
                    f"⭐⭐⭐ SWARM EXECUTION {action.upper()} | {symbol} | {trigger_name} ⭐⭐⭐"
                )
                
                self.active_trade = {'action': action, 'entry': price, 'target': target_time, 'symbol': symbol, 'stake': 0.0, 'placed_at': now}
                self.last_trade_time[symbol] = now
                
                if browser_agent:
                    # Execute the trade first (with CSPRNG execution jitter), THEN notify on success
                    async def _execute_and_notify(ba, act, pr, sym, notif, active_ref, engine_ref):
                        try:
                            # Apply CSPRNG sub-second cryptographic execution jitter (50ms - 180ms)
                            jitter_s = await engine_ref.csprng.apply_jitter(0.05, 0.18)
                            logger.info(f"🎲 [{sym}] CSPRNG Jitter applied: +{jitter_s*1000:.1f}ms order delay")
                            
                            stake = await ba.execute_trade(act, pr)
                            if stake > 0 and active_ref.get('action'):
                                active_ref['stake'] = stake
                                if notif:
                                    await notif.alert_trade_placed(sym, act)
                            else:
                                logger.warning(f"[{sym}] Trade execution returned 0 stake — NOT notifying.")
                        except Exception as e:
                            logger.error(f"[{sym}] Trade execution failed: {e} — NOT notifying.")
                    
                    asyncio.create_task(_execute_and_notify(
                        browser_agent, action, price, symbol, self.notifier, self.active_trade, self
                    ))
                elif self.notifier:
                    # No browser agent (headless/sim mode) — notify immediately
                    asyncio.create_task(self.notifier.alert_trade_placed(symbol, action))
