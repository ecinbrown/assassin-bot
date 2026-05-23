import asyncio
import numpy as np
import time
import csv
import os
import atexit
import logging
from database import insert_tick

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


class LogicEngine:
    """
    ═══════════════════════════════════════════════════════════
      DUAL-ENGINE: W%R Snap + PRNG RTO Pullback
      
      Engine 1: Williams %R(14) extreme + 4 consecutive candles
               → Fade the move, 30s expiry
      
      Engine 2: 0/3 Origin Crossing in Min 1 → Pullback in Min 2
               → Continuation trade, Clock Mode expiry
    ═══════════════════════════════════════════════════════════
    """
    def __init__(self, target_symbols: list = None, notifier=None):
        self.target_symbols = target_symbols if target_symbols else []
        self.notifier = notifier
        self.paused = False
        self.last_prices = {}
        
        # 1-Minute Candle Builder
        self.candle_buffer = {}    # symbol -> list of completed candles
        self.current_candle = {}   # symbol -> {open, high, low, close, minute_key}
        
        # PRNG RTO Tracker
        self.rto_blocks = {}       # symbol -> {block_key, origin_price, crossings, is_armed, direction, min1_close, last_tick_pos}
        self.macro_rto_blocks = {} # symbol -> 15-min macro tracking
        
        # Trade cooldown
        self.last_trade_time = {}
        self.COOLDOWN_SECONDS = 35  # Slightly longer than 30s expiry
        
        # Trade State
        self.active_trade = None
        self.coordinator = None
        
        # Stats
        self.signals_fired = 0
        self.wins = 0
        self.losses = 0

    def _update_candle(self, symbol, price, timestamp):
        """Build 1-minute candles from raw ticks."""
        minute_key = int(timestamp) // 60
        
        if symbol not in self.current_candle or self.current_candle[symbol] is None:
            # First tick ever for this symbol
            self.current_candle[symbol] = {
                'open': price, 'high': price, 'low': price, 'close': price,
                'minute_key': minute_key
            }
            if symbol not in self.candle_buffer:
                self.candle_buffer[symbol] = []
            return None  # No completed candle yet
        
        cc = self.current_candle[symbol]
        
        if minute_key == cc['minute_key']:
            # Same minute — update OHLC
            cc['high'] = max(cc['high'], price)
            cc['low'] = min(cc['low'], price)
            cc['close'] = price
            return None
        else:
            # New minute! Close the old candle and start a new one
            completed = dict(cc)
            self.candle_buffer[symbol].append(completed)
            
            # Keep last 250 candles max to support 200-period historical tracking
            if len(self.candle_buffer[symbol]) > 250:
                self.candle_buffer[symbol].pop(0)
            
            # Start new candle
            self.current_candle[symbol] = {
                'open': price, 'high': price, 'low': price, 'close': price,
                'minute_key': minute_key
            }
            return completed

    def _calc_williams_r(self, candles, period=14):
        """Calculate Williams %R for the most recent candle."""
        if len(candles) < period:
            return None
        
        recent = candles[-period:]
        highest_high = max(c['high'] for c in recent)
        lowest_low = min(c['low'] for c in recent)
        
        if highest_high == lowest_low:
            return -50  # Neutral
        
        current_close = candles[-1]['close']
        wr = (highest_high - current_close) / (highest_high - lowest_low) * -100
        return wr

    def _calc_rsi(self, candles, period=14):
        if len(candles) < period + 1:
            return None
            
        closes = [c['close'] for c in candles[-(period+1):]]
        changes = np.diff(closes)
        
        gains = np.where(changes > 0, changes, 0)
        losses = np.where(changes < 0, -changes, 0)
        
        avg_gain = np.mean(gains)
        avg_loss = np.mean(losses)
        
        if avg_loss == 0:
            return 100
            
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calc_bollinger_bands(self, candles, period=20, std_dev=2.5):
        if len(candles) < period:
            return None, None
            
        closes = [c['close'] for c in candles[-period:]]
        sma = np.mean(closes)
        std = np.std(closes)
        
        upper_bb = sma + (std * std_dev)
        lower_bb = sma - (std * std_dev)
        
        return upper_bb, lower_bb

    def _count_consecutive(self, candles):
        """Count consecutive same-direction candles at the end of the buffer.
        Returns (count, direction) where direction is 'green' or 'red'."""
        if len(candles) < 2:
            return 0, None
        
        last = candles[-1]
        last_dir = 'green' if last['close'] > last['open'] else 'red'
        
        count = 1
        for i in range(len(candles) - 2, -1, -1):
            c = candles[i]
            c_dir = 'green' if c['close'] > c['open'] else 'red'
            if c_dir == last_dir:
                count += 1
            else:
                break
        
        return count, last_dir

    def _check_compression(self, candles):
        """
        Check if the market is in a compressed state.
        Calculates the 20-period standard deviation over a 200-period history.
        Returns True if the current 20-period stddev is below the 10th percentile (p10).
        """
        # Need at least 220 candles (200 history + 20 for the window)
        if len(candles) < 220:
            return False, 0.0, 0.0
            
        stddev_history = []
        # Calculate historical 20-period stddevs for the past 200 periods
        for i in range(200, 0, -1):
            window = [c['close'] for c in candles[-(i+20):-i]]
            if len(window) == 20:
                stddev_history.append(np.std(window))
                
        if len(stddev_history) < 20:
            return False, 0.0, 0.0
            
        # Current 20-period stddev
        current_window = [c['close'] for c in candles[-20:]]
        current_stddev = np.std(current_window)
        
        # 10th percentile threshold (tightest 10% of historical volatility)
        p10_stddev = np.percentile(stddev_history, 10)
        
        is_compressed = current_stddev <= p10_stddev
        return is_compressed, current_stddev, p10_stddev

    def _evaluate_trades(self, current_time, price, browser_agent=None):
        """Resolve active trade at expiry."""
        if self.active_trade and current_time >= self.active_trade['target']:
            action = self.active_trade['action']
            entry = self.active_trade['entry']
            
            win = False
            if action == "call" and price > entry: win = True
            elif action == "put" and price < entry: win = True
            
            if win:
                self.wins += 1
                logger.info(f"💰 WIN! Record: {self.wins}W/{self.losses}L ({self.wins/(self.wins+self.losses)*100:.0f}%)")
                if self.coordinator:
                    self.coordinator.report_win()
                if self.notifier:
                    asyncio.create_task(self.notifier.alert_trade_result(
                        self.active_trade.get('symbol', 'ASSET'), action, True, False
                    ))
            else:
                self.losses += 1
                stake_lost = self.active_trade.get('stake', 0.0)
                logger.warning(f"📉 LOSS. Record: {self.wins}W/{self.losses}L ({self.wins/(self.wins+self.losses)*100:.0f}%)")
                if self.coordinator:
                    self.coordinator.report_loss(stake_lost)
                    if hasattr(self.coordinator, 'martingale_armed'):
                        self.coordinator.martingale_armed = False
                if self.notifier:
                    asyncio.create_task(self.notifier.alert_trade_result(
                        self.active_trade.get('symbol', 'ASSET'), action, False, False
                    ))
                
            self.active_trade = None

    async def process_tick_stream(self, tick_queue: asyncio.Queue, browser_agent=None):
        global _csv_flush_counter
        
        logger.info("═══════════════════════════════════════════════════")
        logger.info("  QUAD-ENGINE: VIP 15M + W%R Snap + PRNG + Macro")
        logger.info("  Engine 1: Williams %%R(14) extreme + 4 Consec (30s)")
        logger.info("  Engine 2: 0/3 Crossing Pullback (Clock Mode)")
        logger.info("  Engine 3: 15-Min Macro Structural (1 Crossing -> UP)")
        logger.info("  Engine 4: VIP 15M (RSI > 75 + BB 2.5) -> Reversal")
        logger.info("═══════════════════════════════════════════════════")
        
        while True:
            tick = await tick_queue.get()
            
            if self.paused:
                continue
                
            symbol = tick.get('symbol')
            if self.target_symbols and symbol not in self.target_symbols:
                continue
                
            price = float(tick.get('price'))
            timestamp = tick.get('timestamp')
            
            # Initialize
            if symbol not in self.last_prices:
                self.last_prices[symbol] = None
                self.last_trade_time[symbol] = 0
                
            velocity = 0.0
            last_price = self.last_prices[symbol]
            if last_price is not None:
                velocity = price - last_price
            self.last_prices[symbol] = price
            
            # Log tick (batched flush every N ticks)
            _tick_writer.writerow([timestamp, symbol, price, velocity])
            _csv_flush_counter += 1
            if _csv_flush_counter >= _CSV_FLUSH_INTERVAL:
                _tick_file.flush()
                _csv_flush_counter = 0
            
            # Evaluate outstanding trades
            self._evaluate_trades(time.time(), price, browser_agent)
            
            insert_tick(timestamp, symbol, price, abs(velocity))
            
            # ═══════════════════════════════════════
            # PRNG STRUCTURAL RTO TRACKING (Tick-by-Tick)
            # ═══════════════════════════════════════
            block_key = int(timestamp) // 300
            minute_of_block = (int(timestamp) % 300) // 60
            
            if symbol not in self.rto_blocks:
                self.rto_blocks[symbol] = {
                    'block_key': block_key, 'origin_price': price, 'crossings': 0,
                    'is_armed': False, 'direction': None, 'min1_close': None,
                    'last_tick_pos': 0
                }
            
            r_state = self.rto_blocks[symbol]
            
            # Reset on new 5-minute block
            if block_key > r_state['block_key']:
                r_state.update({
                    'block_key': block_key, 'origin_price': price, 'crossings': 0,
                    'is_armed': False, 'direction': None, 'min1_close': None,
                    'last_tick_pos': 0
                })
            
            # Minute 1: Track crossings
            if minute_of_block == 0:
                current_pos = 1 if price > r_state['origin_price'] else (-1 if price < r_state['origin_price'] else 0)
                if r_state['last_tick_pos'] != 0 and current_pos != 0 and current_pos != r_state['last_tick_pos']:
                    r_state['crossings'] += 1
                if current_pos != 0:
                    r_state['last_tick_pos'] = current_pos

            # ═══════════════════════════════════════
            # MACRO 15-MIN RTO TRACKING (Tick-by-Tick)
            # ═══════════════════════════════════════
            macro_block_key = int(timestamp) // 900
            minute_of_macro = (int(timestamp) % 900) // 60
            
            if symbol not in self.macro_rto_blocks:
                self.macro_rto_blocks[symbol] = {
                    'block_key': macro_block_key, 'origin_price': price, 'crossings': 0,
                    'is_armed': False, 'direction': None, 'min2_close': None,
                    'last_tick_pos': 0
                }
            
            m_state = self.macro_rto_blocks[symbol]
            
            if macro_block_key > m_state['block_key']:
                m_state.update({
                    'block_key': macro_block_key, 'origin_price': price, 'crossings': 0,
                    'is_armed': False, 'direction': None, 'min2_close': None,
                    'last_tick_pos': 0
                })
                
            # Track crossings in first 2 minutes (Minute 0 and Minute 1)
            if minute_of_macro < 2:
                current_pos = 1 if price > m_state['origin_price'] else (-1 if price < m_state['origin_price'] else 0)
                if m_state['last_tick_pos'] != 0 and current_pos != 0 and current_pos != m_state['last_tick_pos']:
                    m_state['crossings'] += 1
                if current_pos != 0:
                    m_state['last_tick_pos'] = current_pos

            # ═══════════════════════════════════════
            # BUILD 1-MINUTE CANDLES FROM TICKS
            # ═══════════════════════════════════════
            completed_candle = self._update_candle(symbol, price, timestamp)
            candles = self.candle_buffer.get(symbol, [])
            
            # Minute 1 -> Minute 2 Transition (Arming Phase)
            if completed_candle and minute_of_block == 1 and not r_state['is_armed']:
                # Ensure we have enough history to check BB
                is_comp, _, _ = self._check_compression(candles)
                if r_state['crossings'] in [0, 3]:
                    r_state['is_armed'] = True
                    r_state['min1_close'] = completed_candle['close']
                    r_state['direction'] = "UP" if completed_candle['close'] > r_state['origin_price'] else "DOWN"
                    r_state['armed_bb_compressed'] = is_comp
                    logger.info(f"🔫 [RTO ARMED] {symbol} | {r_state['crossings']} Cross | Dir: {r_state['direction']} | Origin: {r_state['origin_price']:.5f} | Min1 Close: {r_state['min1_close']:.5f} | BB Comp: {is_comp}")

            # Macro Minute 2 -> Minute 3 Transition (Arming Phase)
            if completed_candle and minute_of_macro == 2 and not m_state['is_armed']:
                if m_state['crossings'] == 1:
                    m_state['min2_close'] = completed_candle['close']
                    m_state['direction'] = "UP" if m_state['min2_close'] > m_state['origin_price'] else "DOWN"
                    
                    # 100% win rate pattern was exclusively UP
                    if m_state['direction'] == "UP":
                        m_state['is_armed'] = True
                        logger.info(f"🌟 [MACRO ARMED] {symbol} | {m_state['crossings']} Cross | Dir: UP | Origin: {m_state['origin_price']:.5f} | Min2 Close: {m_state['min2_close']:.5f}")

            action = None
            trigger_name = ""
            is_rto_trade = False
            is_macro_trade = False

            # ═══════════════════════════════════════
            # RTO MID-MINUTE EXECUTION
            # ═══════════════════════════════════════
            if minute_of_block == 1 and r_state['is_armed']:
                bb_str = "BB Comp" if r_state.get('armed_bb_compressed') else "Baseline"
                if r_state['direction'] == "UP":
                    if price <= r_state['origin_price']:
                        r_state['is_armed'] = False
                        logger.warning(f"❌ [RTO ABORT] {symbol} - Pulled back and touched origin!")
                    elif price < r_state['min1_close']:
                        action = "call"
                        trigger_name = f"RTO PULLBACK (UP) - {r_state['crossings']} Cross, {bb_str}"
                        r_state['is_armed'] = False  # Disarm after firing
                        is_rto_trade = True
                        
                elif r_state['direction'] == "DOWN":
                    if price >= r_state['origin_price']:
                        r_state['is_armed'] = False
                        logger.warning(f"❌ [RTO ABORT] {symbol} - Pulled back and touched origin!")
                    elif price > r_state['min1_close']:
                        action = "put"
                        trigger_name = f"RTO PULLBACK (DOWN) - {r_state['crossings']} Cross, {bb_str}"
                        r_state['is_armed'] = False
                        is_rto_trade = True

            # ═══════════════════════════════════════
            # MACRO 15-MIN PULLBACK EXECUTION
            # ═══════════════════════════════════════
            if minute_of_macro >= 2 and m_state['is_armed']:
                if price <= m_state['origin_price']:
                    m_state['is_armed'] = False
                    logger.warning(f"❌ [MACRO ABORT] {symbol} - Pulled back and touched origin!")
                elif price < m_state['min2_close']:
                    action = "call"
                    trigger_name = f"MACRO 15M PULLBACK (UP) - {m_state['crossings']} Cross"
                    m_state['is_armed'] = False
                    is_macro_trade = True

            # ═══════════════════════════════════════
            # W%R END-OF-MINUTE EXECUTION
            # ═══════════════════════════════════════
            if not action and completed_candle and len(candles) >= 14:
                wr = self._calc_williams_r(candles, 14)
                if wr is not None:
                    consec_count, consec_dir = self._count_consecutive(candles)
                    is_compressed, cur_std, p10_std = self._check_compression(candles)
                    comp_status = "COMPRESSED" if is_compressed else "WIDE"
                    
                    logger.info(
                        f"📊 [{symbol}] WR={wr:.1f} | Consec: {consec_count} {consec_dir or 'N/A'} | "
                        f"BB: {comp_status} | Price: {price:.5f} | Candles: {len(candles)}"
                    )
                    
                    if is_compressed:
                        if wr > -5 and consec_count >= 4 and consec_dir == 'green':
                            action = "put"
                            trigger_name = f"WR OVERBOUGHT SNAP (WR={wr:.1f}, {consec_count} Green, BB Comp)"
                        elif wr < -95 and consec_count >= 4 and consec_dir == 'red':
                            action = "call"
                            trigger_name = f"WR OVERSOLD SNAP (WR={wr:.1f}, {consec_count} Red, BB Comp)"
                            
            # ═══════════════════════════════════════
            # VIP 15-MINUTE REVERSAL EXECUTION (87.5% WR)
            # ═══════════════════════════════════════
            is_vip_trade = False
            if not action and completed_candle and len(candles) >= 20:
                rsi = self._calc_rsi(candles, 14)
                upper_bb, lower_bb = self._calc_bollinger_bands(candles, 20, 2.5)
                
                if rsi is not None and upper_bb is not None:
                    # PUT Logic: RSI Overbought & Price Pierces Upper BB
                    if rsi >= 75 and price >= upper_bb:
                        action = "put"
                        trigger_name = f"VIP REVERSAL (PUT) - RSI: {rsi:.1f}, BB Pierce"
                        is_vip_trade = True
                        
                    # CALL Logic: RSI Oversold & Price Pierces Lower BB
                    elif rsi <= 25 and price <= lower_bb:
                        action = "call"
                        trigger_name = f"VIP REVERSAL (CALL) - RSI: {rsi:.1f}, BB Pierce"
                        is_vip_trade = True
            
            # If no signal generated from either engine, move to next tick
            if not action:
                continue

            # ═══════════════════════════════════════
            # EXECUTE
            # ═══════════════════════════════════════
            now = time.time()
            elapsed = now - self.last_trade_time.get(symbol, 0)
            
            # Force-clear stuck trades older than 90s
            if self.active_trade and (now - self.active_trade.get('placed_at', now)) > 90:
                logger.warning(f"⚠️ Force-clearing stuck trade (>90s old)")
                self.active_trade = None
            
            # Enforce cooldown and single-trade limit
            if elapsed < self.COOLDOWN_SECONDS:
                logger.debug(f"🕐 Signal blocked by cooldown ({elapsed:.0f}s < {self.COOLDOWN_SECONDS}s)")
                continue
            if self.active_trade is not None:
                logger.debug(f"🔒 Signal blocked — active trade pending")
                continue
            if hasattr(self, 'blocked_symbols') and symbol in self.blocked_symbols:
                logger.warning(f"🚫 Signal blocked — {symbol} payout is below 92%!")
                continue
            
            # Set expiry based on trade type
            if is_rto_trade:
                # Clock Mode: expires at the end of Minute 2 of the current 5-min block
                block_start = int(timestamp) - (int(timestamp) % 300)
                target_time = block_start + 120  # End of Minute 2
                if target_time <= now: target_time = now + 30.0
            elif is_macro_trade:
                # Clock Mode: expires at the end of the current 15-min block
                block_start = int(timestamp) - (int(timestamp) % 900)
                target_time = block_start + 900  # End of 15-min block
                if target_time <= now: target_time = now + 60.0
            elif is_vip_trade:
                # VIP Trade: strict 15-minute timer (900 seconds)
                target_time = now + 900.0
            else:
                # W%R trade: 30-second timer expiry
                target_time = now + 30.0
            
            self.signals_fired += 1
            logger.critical(
                f"⭐⭐⭐ SIGNAL #{self.signals_fired}: {action.upper()} | {symbol} | {trigger_name} ⭐⭐⭐"
            )
            
            self.active_trade = {
                'action': action,
                'entry': price,
                'target': target_time,
                'symbol': symbol,
                'stake': 0.0,
                'placed_at': now,
                'trigger': trigger_name
            }
            self.last_trade_time[symbol] = now
            
            if browser_agent:
                asyncio.create_task(self._execute_and_notify(
                    browser_agent, action, price, symbol, self.notifier, self.active_trade
                ))
            elif hasattr(self, 'trade_api'):
                # WebSocket execution mode
                asyncio.create_task(self.trade_api.execute_trade(
                    action, price, symbol, 
                    duration_sec=int(target_time - now)
                ))
                if self.notifier:
                    asyncio.create_task(self.notifier.alert_trade_placed(symbol, action))
            elif self.notifier:
                asyncio.create_task(self.notifier.alert_trade_placed(symbol, action))

    async def _execute_and_notify(self, ba, act, pr, sym, notif, active_ref):
        """Execute trade via browser and notify on Telegram."""
        try:
            stake = await ba.execute_trade(act, pr)
            if stake > 0 and active_ref.get('action'):
                active_ref['stake'] = stake
                if notif:
                    await notif.alert_trade_placed(sym, act)
            else:
                logger.warning(f"[{sym}] Trade returned 0 — NOT notifying.")
        except Exception as e:
            logger.error(f"[{sym}] Trade execution failed: {e}")
