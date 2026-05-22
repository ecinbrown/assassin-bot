import sys
import time
from datetime import datetime, timezone, timedelta
from assassin_bot import AssassinBot
from hyperliquid.info import Info
from hyperliquid.utils import constants

TARGET_COINS = ["SOL", "ETH", "DOGE", "WIF"]

def check_past_11_hours():
    print("Initializing API...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    bot = AssassinBot(paper_mode=True, starting_balance=100.0)
    
    now = int(datetime.now(timezone.utc).timestamp() * 1000)
    # 11 hours = 132 5-minute candles
    # Plus 220 lookback = 352 candles total
    start = now - (352 * 5 * 60 * 1000)
    
    total_signals = 0
    
    for coin in TARGET_COINS:
        print(f"\nFetching {coin} candles for past 11 hours...")
        try:
            candles = info.candles_snapshot(coin, "5m", start, now)
            parsed = []
            for c in candles:
                parsed.append({
                    'time': c.get('t', c.get('T', 0)),
                    'open': float(c.get('o', c.get('open', 0))),
                    'high': float(c.get('h', c.get('high', 0))),
                    'low': float(c.get('l', c.get('low', 0))),
                    'close': float(c.get('c', c.get('close', 0))),
                    'volume': float(c.get('v', c.get('volume', 0))),
                })
            parsed.sort(key=lambda x: x['time'])
            
            print(f"Loaded {len(parsed)} candles. Scanning...")
            
            signals_for_coin = 0
            
            # Iterate through the past 132 candles (11 hours)
            for i in range(220, len(parsed)):
                window = parsed[:i+1] # up to the current candle in the loop
                
                # Check signal
                signal = bot._compute_signals(window)
                if signal is not None:
                    should_trade, direction, confirmations, tp_price, sl_price, sl_dist, tp_dist = signal
                    candle_time = datetime.fromtimestamp(window[-1]['time']/1000, tz=timezone.utc)
                    print(f"  [SIGNAL FIRE] {coin} {direction} @ {candle_time.strftime('%Y-%m-%d %H:%M:%S')} UTC")
                    print(f"    Entry: {window[-1]['close']:.4f} | TP: {tp_price:.4f} | SL: {sl_price:.4f}")
                    signals_for_coin += 1
                    total_signals += 1
                    
            if signals_for_coin == 0:
                print(f"  No signals for {coin} in the past 11 hours.")
                
        except Exception as e:
            print(f"Error checking {coin}: {e}")

    print(f"\nTotal signals across all targets in 11h: {total_signals}")

if __name__ == '__main__':
    check_past_11_hours()
