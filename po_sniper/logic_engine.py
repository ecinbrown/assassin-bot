import asyncio
import numpy as np
import time
import csv
import os
import atexit
import logging
from collections import deque
from database import insert_tick
from velocity_config import (
    get_tier, TIER_CANDLE_WINDOWS, TIER_STRATEGIES,
    KILL_SWITCH, EXPIRY_MULTIPLIER, COOLDOWN_MULTIPLIER,
    TIER_TRADE_SIZE
)

logger = logging.getLogger(__name__)

# Tick logger - appends every tick to CSV for analysis
TICK_LOG_PATH = os.path.join(os.path.dirname(__file__), "tick_log.csv")
_need_header = not os.path.exists(TICK_LOG_PATH) or os.path.getsize(TICK_LOG_PATH) == 0
_tick_file = open(TICK_LOG_PATH, "a", newline="")
_tick_writer = csv.writer(_tick_file)
if _need_header:
    _tick_writer.writerow(["timestamp", "symbol", "price", "velocity"])
    _tick_file.flush()

# Flush counter for batched CSV writes
_csv_flush_counter = 0
_CSV_FLUSH_INTERVAL = 10

# Ensure CSV file is properly closed on exit
def _cleanup_tick_file():
    try:
        _tick_file.flush()
        _tick_file.close()
    except Exception:
        pass
atexit.register(_cleanup_tick_file)


class VelocityCandle:
    """Aggregates raw ticks into a velocity-enhanced candle."""
    __slots__ = ['open', 'high', 'low', 'close', 'vel_sum', 'vel_abs_sum',
                 'vel_abs_values', 'tick_count', 'window_key']
    
    def __init__(self, price, velocity, window_key):
        self.open = price
        self.high = price
        self.low = price
        self.close = price
        self.vel_sum = velocity
        self.vel_abs_sum = abs(velocity)
        self.vel_abs_values = [abs(velocity)]
        self.tick_count = 1
        self.window_key = window_key
    
    def update(self, price, velocity):
        self.high = max(self.high, price)
        self.low = min(self.low, price)
        self.close = price
        self.vel_sum += velocity
        self.vel_abs_sum += abs(velocity)
        self.vel_abs_values.append(abs(velocity))
        self.tick_count += 1
    
    @property
    def vel_abs_mean(self):
        return self.vel_abs_sum / self.tick_count if self.tick_count > 0 else 0.0
    
    @property
    def vel_spike_count(self):
        if len(self.vel_abs_values) < 2:
            return 0
        median = np.median(self.vel_abs_values)
        if median == 0:
            return 0
        return sum(1 for v in self.vel_abs_values if v > 2 * median)
    
    @property
    def vel_std(self):
        if len(self.vel_abs_values) < 2:
            return 0.0
        return float(np.std(self.vel_abs_values))


class LogicEngine:
    """
    ═══════════════════════════════════════════════════════════
      VELOCITY EDGE ENGINE: 3-Tier Hybrid Strategy System
      
      Tier 1 (AEDCNY): RSI+Vel, VelSpike, TickDensity, VelEnergy
      Tier 2 (AUDCAD, AUDJPY): VelSpike, VelEnergy
      Tier 3 (All others): VelSpike only (conservative)
      
      Backtested: 80-93% WR on proven pairs
      Kill switch: auto-pause if WR < 60% over last 20 trades
    ═══════════════════════════════════════════════════════════
    """
    def __init__(self, target_symbols: list = None, notifier=None):
        self.target_symbols = target_symbols if target_symbols else []
        self.notifier = notifier
        self.paused = False
        self.last_prices = {}
        
        # Multi-timeframe velocity candle builders
        # Structure: {symbol: {window_minutes: {'current': VelocityCandle, 'buffer': deque}}}
        self.vel_candles = {}
        
        # Per-symbol trade cooldown
        self.last_trade_time = {}
        
        # Per-symbol active trades (supports concurrent trades on different symbols)
        self.active_trades = {}
        
        # Trade coordinator
        self.coordinator = None
        
        # Stats per tier
        self.tier_stats = {1: deque(maxlen=100), 2: deque(maxlen=100), 3: deque(maxlen=100)}
        self.tier_paused = {1: False, 2: False, 3: False}
        
        # Global stats
        self.signals_fired = 0
        self.wins = 0
        self.losses = 0

    def _init_symbol(self, symbol):
        """Initialize candle builders for a symbol across all its tier's timeframes."""
        if symbol in self.vel_candles:
            return
        
        tier = get_tier(symbol)
        windows = TIER_CANDLE_WINDOWS.get(tier, [6, 9])
        
        self.vel_candles[symbol] = {}
        for w in windows:
            self.vel_candles[symbol][w] = {
                'current': None,
                'buffer': deque(maxlen=50)  # Keep last 50 candles per timeframe
            }
        
        self.last_prices[symbol] = None
        self.last_trade_time[symbol] = 0

    def _update_velocity_candle(self, symbol, price, velocity, timestamp, window_minutes):
        """Build velocity-enhanced candles from raw ticks for a specific timeframe."""
        window_seconds = window_minutes * 60
        window_key = int(timestamp) // window_seconds
        
        store = self.vel_candles[symbol][window_minutes]
        
        if store['current'] is None:
            store['current'] = VelocityCandle(price, velocity, window_key)
            return None
        
        if window_key == store['current'].window_key:
            store['current'].update(price, velocity)
            return None
        else:
            completed = store['current']
            store['buffer'].append(completed)
            store['current'] = VelocityCandle(price, velocity, window_key)
            return completed

    # ═══════════════════════════════════════════════════
    # INDICATOR CALCULATIONS
    # ═══════════════════════════════════════════════════
    
    def _calc_rsi(self, candles, period=14):
        """Calculate RSI from a list of VelocityCandle objects."""
        if len(candles) < period + 1:
            return None
        closes = [c.close for c in list(candles)[-(period+1):]]
        changes = np.diff(closes)
        gains = np.where(changes > 0, changes, 0)
        losses_arr = np.where(changes < 0, -changes, 0)
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses_arr)
        if avg_loss == 0:
            return 100
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # ═══════════════════════════════════════════════════
    # VELOCITY SIGNAL GENERATORS
    # ═══════════════════════════════════════════════════

    def _check_vel_spike(self, candles, config):
        """Velocity spikes above rolling average -> exhaustion reversal."""
        if not config.get('enabled'):
            return None
        
        lookback = config['lookback']
        spike_mult = config['spike_mult']
        
        if len(candles) < lookback + 1:
            return None
        
        candle_list = list(candles)
        current = candle_list[-1]
        history = candle_list[-(lookback + 1):-1]
        
        vel_abs_means = [c.vel_abs_mean for c in history]
        avg = np.mean(vel_abs_means)
        std = np.std(vel_abs_means)
        
        if std == 0 or avg == 0:
            return None
        
        if current.vel_abs_mean > avg + spike_mult * std:
            if current.vel_sum > 0:
                return 'put'   # Fast move up -> exhaustion -> reversal down
            else:
                return 'call'  # Fast move down -> exhaustion -> reversal up
        
        return None

    def _check_rsi_vel(self, candles, config):
        """RSI extreme + velocity spike confirmation."""
        if not config.get('enabled'):
            return None
        
        rsi_period = config['rsi_period']
        rsi_os = config['rsi_oversold']
        rsi_ob = config['rsi_overbought']
        vel_lb = config['vel_lookback']
        vel_thresh = config['vel_threshold']
        
        if len(candles) < max(rsi_period + 1, vel_lb + 1):
            return None
        
        candle_list = list(candles)
        current = candle_list[-1]
        
        rsi = self._calc_rsi(candles, rsi_period)
        if rsi is None:
            return None
        
        # Calculate velocity ratio
        recent_vel = [c.vel_abs_mean for c in candle_list[-(vel_lb + 1):-1]]
        avg_vel = np.mean(recent_vel) if recent_vel else 0
        if avg_vel == 0:
            return None
        
        vel_ratio = current.vel_abs_mean / avg_vel
        
        if rsi < rsi_os and vel_ratio > vel_thresh:
            return 'call'
        elif rsi > rsi_ob and vel_ratio > vel_thresh:
            return 'put'
        
        return None

    def _check_tick_density(self, candles, config):
        """Abnormal tick count -> unusual activity -> exhaustion."""
        if not config.get('enabled'):
            return None
        
        lookback = config['lookback']
        density_mult = config['density_mult']
        
        if len(candles) < lookback + 1:
            return None
        
        candle_list = list(candles)
        current = candle_list[-1]
        history = candle_list[-(lookback + 1):-1]
        
        counts = [c.tick_count for c in history]
        avg = np.mean(counts)
        std = np.std(counts)
        
        if std == 0:
            return None
        
        # High tick density = unusual activity
        if current.tick_count > avg + density_mult * std:
            if current.vel_sum > 0:
                return 'put'
            else:
                return 'call'
        
        return None

    def _check_vel_energy(self, candles, config):
        """Total velocity energy burst -> exhaustion reversal."""
        if not config.get('enabled'):
            return None
        
        lookback = config['lookback']
        burst_mult = config['burst_mult']
        
        if len(candles) < lookback + 1:
            return None
        
        candle_list = list(candles)
        current = candle_list[-1]
        history = candle_list[-(lookback + 1):-1]
        
        energy_vals = [c.vel_abs_sum for c in history]
        avg_energy = np.mean(energy_vals)
        
        if avg_energy == 0:
            return None
        
        if current.vel_abs_sum > burst_mult * avg_energy:
            if current.vel_sum > 0:
                return 'put'
            else:
                return 'call'
        
        return None

    # ═══════════════════════════════════════════════════
    # KILL SWITCH
    # ═══════════════════════════════════════════════════

    def _check_kill_switch(self, tier):
        """Check if a tier should be paused based on recent performance."""
        if not KILL_SWITCH['enabled']:
            return False
        
        results = self.tier_stats[tier]
        if len(results) < KILL_SWITCH['min_trades']:
            return False
        
        recent = list(results)[-KILL_SWITCH['window_size']:]
        if len(recent) < KILL_SWITCH['min_trades']:
            return False
        
        win_rate = sum(recent) / len(recent) * 100
        
        if win_rate < KILL_SWITCH['min_win_rate']:
            if not self.tier_paused[tier]:
                logger.critical(
                    f"KILL SWITCH: Tier {tier} PAUSED! WR={win_rate:.1f}% "
                    f"(below {KILL_SWITCH['min_win_rate']}% over last {len(recent)} trades)"
                )
                self.tier_paused[tier] = True
            return True
        else:
            if self.tier_paused[tier]:
                logger.info(f"Tier {tier} RESUMED! WR={win_rate:.1f}% recovered above threshold")
                self.tier_paused[tier] = False
            return False

    # ═══════════════════════════════════════════════════
    # TRADE EVALUATION
    # ═══════════════════════════════════════════════════

    def _evaluate_trades(self, current_time, symbol, price):
        """Resolve active trade for a symbol at expiry."""
        if symbol not in self.active_trades:
            return
        
        trade = self.active_trades[symbol]
        if current_time < trade['target']:
            return
        
        action = trade['action']
        entry = trade['entry']
        tier = trade['tier']
        
        win = False
        if action == "call" and price > entry:
            win = True
        elif action == "put" and price < entry:
            win = True
        
        # Record result for kill switch
        self.tier_stats[tier].append(1 if win else 0)
        
        if win:
            self.wins += 1
            total = self.wins + self.losses
            logger.info(
                f"WIN! [{symbol}] Tier {tier} | "
                f"Record: {self.wins}W/{self.losses}L ({self.wins/total*100:.0f}%)"
            )
            if self.coordinator:
                self.coordinator.report_win()
            if self.notifier:
                asyncio.create_task(self.notifier.alert_trade_result(
                    symbol, action, True, False
                ))
        else:
            self.losses += 1
            stake_lost = trade.get('stake', 0.0)
            total = self.wins + self.losses
            logger.warning(
                f"LOSS. [{symbol}] Tier {tier} | "
                f"Record: {self.wins}W/{self.losses}L ({self.wins/total*100:.0f}%)"
            )
            if self.coordinator:
                self.coordinator.report_loss(stake_lost)
            if self.notifier:
                asyncio.create_task(self.notifier.alert_trade_result(
                    symbol, action, False, False
                ))
        
        del self.active_trades[symbol]

    # ═══════════════════════════════════════════════════
    # MAIN TICK PROCESSING LOOP
    # ═══════════════════════════════════════════════════

    async def process_tick_stream(self, tick_queue: asyncio.Queue, browser_agent=None):
        global _csv_flush_counter
        
        logger.info("=" * 60)
        logger.info("  VELOCITY EDGE ENGINE: 3-Tier Hybrid System")
        logger.info("  Tier 1 (AEDCNY): RSI+Vel, VelSpike, TickDensity, VelEnergy")
        logger.info("  Tier 2 (AUDCAD, AUDJPY): VelSpike, VelEnergy")
        logger.info("  Tier 3 (All others): VelSpike (conservative)")
        logger.info("  Kill switch: auto-pause if WR < 60% over 20 trades")
        logger.info("=" * 60)
        
        while True:
            tick = await tick_queue.get()
            
            if self.paused:
                continue
                
            symbol = tick.get('symbol')
            if self.target_symbols and symbol not in self.target_symbols:
                continue
                
            price = float(tick.get('price'))
            timestamp = tick.get('timestamp')
            
            # Initialize symbol if first tick
            self._init_symbol(symbol)
            
            # Calculate velocity
            velocity = 0.0
            last_price = self.last_prices[symbol]
            if last_price is not None:
                velocity = price - last_price
            self.last_prices[symbol] = price
            
            # Log tick (batched flush)
            _tick_writer.writerow([timestamp, symbol, price, velocity])
            _csv_flush_counter += 1
            if _csv_flush_counter >= _CSV_FLUSH_INTERVAL:
                _tick_file.flush()
                _csv_flush_counter = 0
            
            # Evaluate outstanding trades for this symbol
            self._evaluate_trades(time.time(), symbol, price)
            
            # Insert into database (non-blocking)
            insert_tick(timestamp, symbol, price, abs(velocity))
            
            # ═══════════════════════════════════════
            # BUILD VELOCITY CANDLES + CHECK SIGNALS
            # ═══════════════════════════════════════
            tier = get_tier(symbol)
            
            # Check kill switch
            if self._check_kill_switch(tier):
                continue
            
            # Skip if already have active trade on this symbol
            if symbol in self.active_trades:
                continue
            
            strategies = TIER_STRATEGIES.get(tier, TIER_STRATEGIES[3])
            action = None
            trigger_name = ""
            trigger_window = 0
            
            for window_minutes in TIER_CANDLE_WINDOWS.get(tier, [6, 9]):
                completed = self._update_velocity_candle(
                    symbol, price, velocity, timestamp, window_minutes
                )
                
                if completed is None:
                    continue
                
                candles = self.vel_candles[symbol][window_minutes]['buffer']
                
                if len(candles) < 25:
                    continue
                
                # Check each strategy
                for strat_name, config in strategies.items():
                    if action:
                        break
                    
                    result = None
                    if strat_name == 'vel_spike':
                        result = self._check_vel_spike(candles, config)
                    elif strat_name == 'rsi_vel':
                        result = self._check_rsi_vel(candles, config)
                    elif strat_name == 'tick_density':
                        result = self._check_tick_density(candles, config)
                    elif strat_name == 'vel_energy':
                        result = self._check_vel_energy(candles, config)
                    
                    if result:
                        action = result
                        trigger_window = window_minutes
                        trigger_name = (
                            f"T{tier} {strat_name.upper()} ({action.upper()}) "
                            f"on {window_minutes}min candle"
                        )
                
                if action:
                    break
            
            if not action:
                continue

            # ═══════════════════════════════════════
            # EXECUTE TRADE
            # ═══════════════════════════════════════
            now = time.time()
            
            # Calculate expiry based on candle window
            expiry_seconds = trigger_window * 60 * EXPIRY_MULTIPLIER
            cooldown_seconds = expiry_seconds * COOLDOWN_MULTIPLIER
            
            # Check cooldown
            elapsed = now - self.last_trade_time.get(symbol, 0)
            if elapsed < cooldown_seconds:
                logger.debug(
                    f"[{symbol}] Signal blocked by cooldown "
                    f"({elapsed:.0f}s < {cooldown_seconds:.0f}s)"
                )
                continue
            
            # Check payout block
            if hasattr(self, 'blocked_symbols') and symbol in self.blocked_symbols:
                logger.warning(f"[{symbol}] Signal blocked -- payout below 92%!")
                continue
            
            target_time = now + expiry_seconds
            
            self.signals_fired += 1
            size_mult = TIER_TRADE_SIZE.get(tier, 0.5)
            logger.critical(
                f"SIGNAL #{self.signals_fired}: {action.upper()} | {symbol} | "
                f"{trigger_name} | Expiry: {trigger_window}min | Size: {size_mult}x"
            )
            
            self.active_trades[symbol] = {
                'action': action,
                'entry': price,
                'target': target_time,
                'symbol': symbol,
                'tier': tier,
                'stake': 0.0,
                'size_mult': size_mult,
                'placed_at': now,
                'trigger': trigger_name
            }
            self.last_trade_time[symbol] = now
            
            if browser_agent:
                asyncio.create_task(self._execute_and_notify(
                    browser_agent, action, price, symbol, self.notifier,
                    self.active_trades[symbol]
                ))
            elif self.notifier:
                asyncio.create_task(self.notifier.alert_trade_placed(symbol, action))

    async def _execute_and_notify(self, ba, act, pr, sym, notif, active_ref):
        """Execute trade via WSS agent and notify on Telegram."""
        try:
            stake = await ba.execute_trade(act, pr, sym)
            if stake > 0 and active_ref.get('action'):
                active_ref['stake'] = stake
                if notif:
                    await notif.alert_trade_placed(sym, act)
            else:
                logger.warning(f"[{sym}] Trade returned 0 -- NOT notifying.")
        except Exception as e:
            logger.error(f"[{sym}] Trade execution failed: {e}")
