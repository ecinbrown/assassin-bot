"""
BINANCE 6-MONTH TICK RESOLVER
==============================
Since Hyperliquid caps historical data at ~5,000 candles, we can't do a full
6-month sub-candle backtest using their API. 

This script pulls 6 months of 30m and 5m BTCUSDT data from Binance, applies 
the EXACT Assassin logic (1.5 R:R, ATR 0.5, Wick+Vol checks), and resolves 
the trades stepping forward on the 5m candles.
"""
import time
import requests
import numpy as np
from datetime import datetime, timezone

def fetch_binance_candles(symbol="BTCUSDT", interval="30m", limit_days=180):
    """Fetch continuous historical data from Binance."""
    base_url = "https://api.binance.com/api/v3/klines"
    end_time = int(time.time() * 1000)
    start_time = end_time - (limit_days * 24 * 60 * 60 * 1000)
    
    all_candles = []
    current_start = start_time
    
    print(f"Fetching {limit_days} days of {interval} data from Binance...")
    while current_start < end_time:
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": current_start,
            "limit": 1000
        }
        res = requests.get(base_url, params=params)
        if res.status_code != 200:
            print("Error fetching data:", res.text)
            break
            
        data = res.json()
        if not data:
            break
            
        for c in data:
            all_candles.append({
                'time': c[0],
                'open': float(c[1]),
                'high': float(c[2]),
                'low': float(c[3]),
                'close': float(c[4]),
                'volume': float(c[5])
            })
            
        current_start = data[-1][0] + 1
        time.sleep(0.1) # Be nice to API
        
    print(f"  Got {len(all_candles)} candles.")
    return all_candles

def calculate_atr(candles, idx, period=14):
    start = max(1, idx - period + 1)
    trs = []
    for i in range(start, idx + 1):
        h, l, pc = candles[i]['high'], candles[i]['low'], candles[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs) if trs else 50

def get_signal(candles, i, lookback=20):
    if i < lookback + 3: return None
    c = candles[i]
    prev = candles[i-1]
    
    body = abs(c['close'] - c['open'])
    if body == 0: body = 0.01
    rng = c['high'] - c['low']
    if rng < 50: return None
    
    upper_wick = c['high'] - max(c['open'], c['close'])
    lower_wick = min(c['open'], c['close']) - c['low']
    wick_ratio = max(upper_wick, lower_wick) / body
    wick_dir = "DOWN" if lower_wick > upper_wick else "UP"
    
    vol_window = [candles[j]['volume'] for j in range(i - lookback, i)]
    avg_vol = np.mean(vol_window) if vol_window else 0.01
    vol_ratio = c['volume'] / avg_vol
    
    close_window = [candles[j]['close'] for j in range(i - lookback, i)]
    std_p = np.std(close_window)
    if std_p == 0: std_p = 0.01
    z = (c['close'] - np.mean(close_window)) / std_p
    
    rsi_period = min(14, i)
    gains, loss_arr = [], []
    for j in range(i - rsi_period, i):
        d = candles[j+1]['close'] - candles[j]['close']
        gains.append(max(d, 0))
        loss_arr.append(abs(min(d, 0)))
    avg_g = np.mean(gains) if gains else 0
    avg_l = np.mean(loss_arr) if loss_arr else 0.01
    rsi = 100 - (100 / (1 + avg_g / avg_l))
    
    vel1 = c['close'] - prev['close']
    vel2 = prev['close'] - candles[i-2]['close']
    vel3 = candles[i-2]['close'] - candles[i-3]['close']
    vel_exhaust = (vel1*vel2 > 0) and (vel2*vel3 > 0) and (abs(vel1) > abs(vel2) > abs(vel3))
    
    confirms = 0
    direction = None
    
    if wick_ratio >= 2.0: 
        confirms += 1
        direction = "LONG" if wick_dir == "DOWN" else "SHORT"
    if vol_ratio >= 1.5: 
        confirms += 1
    if vel_exhaust: 
        confirms += 1
    if abs(z) >= 1.5:
        confirms += 1
        if not direction: direction = "SHORT" if z > 0 else "LONG"
    if rsi <= 30 or rsi >= 70:
        confirms += 1
        if not direction: direction = "LONG" if rsi <= 30 else "SHORT"
    
    if direction and confirms >= 2:
        return {'direction': direction, 'confirms': confirms,
                'high': c['high'], 'low': c['low'], 'close': c['close'],
                'candle_time': c['time']}
    return None

def run_binance_backtest():
    print("="*80)
    print(" 6-MONTH VALIDATOR (BINANCE DATA)")
    print(" 30m Signals resolved on 5m Candles")
    print("="*80)
    
    candles_30m = fetch_binance_candles("BTCUSDT", "30m", 180)
    candles_5m = fetch_binance_candles("BTCUSDT", "5m", 180)
    
    wins = 0
    losses = 0
    unresolved = 0
    
    last_entry_time = 0
    
    for i in range(20, len(candles_30m)):
        sig = get_signal(candles_30m, i)
        if not sig: continue
        
        # Prevent same-candle multiple entries
        if sig['candle_time'] <= last_entry_time: continue
        
        entry = sig['close']
        atr = calculate_atr(candles_30m, i)
        direction = sig['direction']
        
        # The exact live bot parameters
        if direction == "LONG":
            sl_dist = abs(entry - sig['low']) + (atr * 0.5)
        else:
            sl_dist = abs(entry - sig['high']) + (atr * 0.5)
            
        sl_dist = max(sl_dist, 10)
        tp_dist = sl_dist * 1.5  # 1.5 R:R
        
        if direction == "LONG":
            tp_price, sl_price = entry + tp_dist, entry - sl_dist
        else:
            tp_price, sl_price = entry - tp_dist, entry + sl_dist
            
        # RESOLVE ON 5m CANDLES
        resolved = False
        
        # Find starting 5m candle
        start_idx = None
        for j, mc in enumerate(candles_5m):
            if mc['time'] > sig['candle_time']:
                start_idx = j
                break
                
        if start_idx is not None:
            for j in range(start_idx, min(start_idx + 1000, len(candles_5m))):
                mc = candles_5m[j]
                if direction == "LONG":
                    if mc['low'] <= sl_price:
                        losses += 1
                        resolved = True
                        break
                    if mc['high'] >= tp_price:
                        wins += 1
                        resolved = True
                        break
                else:
                    if mc['high'] >= sl_price:
                        losses += 1
                        resolved = True
                        break
                    if mc['low'] <= tp_price:
                        wins += 1
                        resolved = True
                        break
                        
        if not resolved:
            unresolved += 1
            
        last_entry_time = sig['candle_time']

    tot = wins + losses
    wr = (wins / tot * 100) if tot > 0 else 0
    
    print("\n" + "="*80)
    print(" 6-MONTH RESULTS (180 DAYS)")
    print("="*80)
    print(f" Total Signals:  {tot + unresolved}")
    print(f" Wins:           {wins}")
    print(f" Losses:         {losses}")
    print(f" Unresolved:     {unresolved}")
    print(f" Win Rate:       {wr:.1f}%")
    
    # Run the compound math
    balance = 10.0
    risk = 0.20
    peak = 10.0
    
    for _ in range(wins):
        balance *= (1 + (risk * 1.5))
        peak = max(peak, balance)
    for _ in range(losses):
        balance *= (1 - risk)
        
    print(f"\n Compounding Map (Flat distribution):")
    print(f" Risk per trade: 20%")
    print(f" $10 Start -> ${balance:,.2f}")
    
run_binance_backtest()
