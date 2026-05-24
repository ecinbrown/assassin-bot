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
      SINGLE ENGINE: VIP 15-Minute Reversal
      
      RSI(14) >= 75 + Price pierces Upper Bollinger Band (2.5σ) → PUT
      RSI(14) <= 25 + Price pierces Lower Bollinger Band (2.5σ) → CALL
      
      Expiry: 15 minutes (900 seconds)
      Backtested Win Rate: 87.5%
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
        
        # Trade cooldown
        self.last_trade_time = {}
        self.COOLDOWN_SECONDS = 900  # 15 minutes — one trade per expiry window
        
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
            self.current_candle[symbol] = {
                'open': price, 'high': price, 'low': price, 'close': price,
                'minute_key': minute_key
            }
            if symbol not in self.candle_buffer:
                self.candle_buffer[symbol] = []
            return None
        
        cc = self.current_candle[symbol]
        
        if minute_key == cc['minute_key']:
            cc['high'] = max(cc['high'], price)
            cc['low'] = min(cc['low'], price)
            cc['close'] = price
            return None
        else:
            completed = dict(cc)
            self.candle_buffer[symbol].append(completed)
            
            # Keep last 250 candles max
            if len(self.candle_buffer[symbol]) > 250:
                self.candle_buffer[symbol].pop(0)
            
            self.current_candle[symbol] = {
                'open': price, 'high': price, 'low': price, 'close': price,
                'minute_key': minute_key
            }
            return completed

    def _calc_rsi(self, candles, period=14):
        """Calculate RSI for the most recent candle."""
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
        """Calculate Bollinger Bands with 2.5 standard deviations."""
        if len(candles) < period:
            return None, None
            
        closes = [c['close'] for c in candles[-period:]]
        sma = np.mean(closes)
        std = np.std(closes)
        
        upper_bb = sma + (std * std_dev)
        lower_bb = sma - (std * std_dev)
        
        return upper_bb, lower_bb

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
                if self.notifier:
                    asyncio.create_task(self.notifier.alert_trade_result(
                        self.active_trade.get('symbol', 'ASSET'), action, False, False
                    ))
                
            self.active_trade = None

    async def process_tick_stream(self, tick_queue: asyncio.Queue, browser_agent=None):
        global _csv_flush_counter
        
        logger.info("═══════════════════════════════════════════════════")
        logger.info("  SINGLE ENGINE: VIP 15-Minute Reversal")
        logger.info("  RSI(14) >= 75 + BB(2.5σ) Pierce → PUT")
        logger.info("  RSI(14) <= 25 + BB(2.5σ) Pierce → CALL")
        logger.info("  Expiry: 15 minutes | Backtested WR: 87.5%")
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
            # BUILD 1-MINUTE CANDLES FROM TICKS
            # ═══════════════════════════════════════
            completed_candle = self._update_candle(symbol, price, timestamp)
            candles = self.candle_buffer.get(symbol, [])
            
            action = None
            trigger_name = ""

            # ═══════════════════════════════════════
            # VIP 15-MINUTE REVERSAL (87.5% WR)
            # RSI(14) >= 75 + Price above Upper BB(2.5σ) → PUT
            # RSI(14) <= 25 + Price below Lower BB(2.5σ) → CALL
            # ═══════════════════════════════════════
            if completed_candle and len(candles) >= 20:
                rsi = self._calc_rsi(candles, 14)
                upper_bb, lower_bb = self._calc_bollinger_bands(candles, 20, 2.5)
                
                if rsi is not None and upper_bb is not None:
                    logger.info(
                        f"📊 [{symbol}] RSI={rsi:.1f} | Price={price:.5f} | "
                        f"Upper BB={upper_bb:.5f} | Lower BB={lower_bb:.5f} | "
                        f"Candles: {len(candles)}"
                    )
                    
                    # PUT: RSI overbought + price pierces upper BB
                    if rsi >= 75 and price >= upper_bb:
                        action = "put"
                        trigger_name = f"VIP REVERSAL (PUT) — RSI: {rsi:.1f}, BB 2.5σ Pierce"
                        
                    # CALL: RSI oversold + price pierces lower BB
                    elif rsi <= 25 and price <= lower_bb:
                        action = "call"
                        trigger_name = f"VIP REVERSAL (CALL) — RSI: {rsi:.1f}, BB 2.5σ Pierce"
            
            if not action:
                continue

            # ═══════════════════════════════════════
            # EXECUTE
            # ═══════════════════════════════════════
            now = time.time()
            elapsed = now - self.last_trade_time.get(symbol, 0)
            
            # Force-clear stuck trades older than 960s (16 min safety)
            if self.active_trade and (now - self.active_trade.get('placed_at', now)) > 960:
                logger.warning(f"⚠️ Force-clearing stuck trade (>960s old)")
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
            
            # 15-minute expiry
            target_time = now + 900.0
            
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
                logger.warning(f"[{sym}] Trade returned 0 — NOT notifying.")
        except Exception as e:
            logger.error(f"[{sym}] Trade execution failed: {e}")
