import sys
import time
import requests
from datetime import datetime, timezone
from assassin_bot import AssassinBot

TARGET_COINS = ["SOLUSDT", "ETHUSDT", "DOGEUSDT", "WIFUSDT", "BTCUSDT"]

def fetch_binance_klines(symbol, interval="5m", limit=1000):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
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

def check_outcomes():
    bot = AssassinBot(paper_mode=True, starting_balance=100.0)
    limit = 808
    
    wins = 0
    losses = 0
    
    for coin in TARGET_COINS:
        try:
            parsed = fetch_binance_klines(coin, "5m", limit)
            parsed.sort(key=lambda x: x['time'])
            
            for i in range(220, len(parsed)):
                window = parsed[:i+1]
                
                signal = bot._compute_signals(window)
                if signal is not None:
                    should_trade, direction, confirmations, tp_price, sl_price, sl_dist, tp_dist = signal
                    
                    # Check future candles for outcome
                    outcome = "PENDING"
                    for j in range(i+1, len(parsed)):
                        future_candle = parsed[j]
                        if direction == "LONG":
                            if future_candle['low'] <= sl_price:
                                outcome = "LOSS"
                                break
                            elif future_candle['high'] >= tp_price:
                                outcome = "WIN"
                                break
                        elif direction == "SHORT":
                            if future_candle['high'] >= sl_price:
                                outcome = "LOSS"
                                break
                            elif future_candle['low'] <= tp_price:
                                outcome = "WIN"
                                break
                                
                    if outcome == "WIN":
                        wins += 1
                    elif outcome == "LOSS":
                        losses += 1
                        
                    print(f"[{outcome}] {coin} {direction} | Entry: {window[-1]['close']} | TP: {tp_price} | SL: {sl_price}")
                    
        except Exception as e:
            pass

    print(f"\nTotal: {wins} Wins, {losses} Losses")

if __name__ == '__main__':
    check_outcomes()
