import sys
import time
import requests
import pandas as pd
from datetime import datetime, timezone, timedelta
from assassin_bot import AssassinBot

TARGET_COINS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "WIFUSDT", "BTCUSDT"]

def fetch_binance_klines(symbol, interval="5m", limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }
    response = requests.get(url, params=params)
    response.raise_for_status()
    data = response.json()
    
    parsed = []
    for c in data:
        parsed.append({
            'time': c[0],
            'open': float(c[1]),
            'high': float(c[2]),
            'low': float(c[3]),
            'close': float(c[4]),
            'volume': float(c[5])
        })
    return parsed

def check_past_19_hours():
    print("Initializing API for Binance...")
    bot = AssassinBot(paper_mode=True, starting_balance=100.0)
    
    # 19 hours = 228 5-minute candles
    # Plus 220 lookback = 448 candles total
    limit = 448
    
    total_signals = 0
    
    for coin in TARGET_COINS:
        print(f"\nFetching {coin} candles for past 19 hours...")
        try:
            parsed = fetch_binance_klines(coin, "5m", limit)
            parsed.sort(key=lambda x: x['time'])
            
            print(f"Loaded {len(parsed)} candles. Scanning...")
            
            signals_for_coin = 0
            
            for i in range(220, len(parsed)):
                window = parsed[:i+1] # up to current candle in loop
                
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
                print(f"  No signals for {coin} in the past 19 hours.")
                
        except Exception as e:
            print(f"Error checking {coin}: {e}")

    print(f"\nTotal signals across all targets in 19h: {total_signals}")

if __name__ == '__main__':
    check_past_19_hours()
