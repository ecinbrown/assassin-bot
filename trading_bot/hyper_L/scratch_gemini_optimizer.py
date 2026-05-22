"""
GEMINI 6-MONTH GRID OPTIMIZER
==============================
Searching for the >52% edge on 1.5+ R:R over 6 months of data.
Tests strict wick/vol requirements and wider ATR stops.
"""
import time
import requests
import numpy as np

def fetch_binance_candles(symbol="BTCUSDT", interval="30m", limit_days=180):
    base_url = "https://api.binance.com/api/v3/klines"
    end_time = int(time.time() * 1000)
    start_time = end_time - (limit_days * 24 * 60 * 60 * 1000)
    all_candles = []
    current_start = start_time
    while current_start < end_time:
        res = requests.get(base_url, params={"symbol": symbol, "interval": interval, "startTime": current_start, "limit": 1000})
        if res.status_code != 200: break
        data = res.json()
        if not data: break
        for c in data:
            all_candles.append({'time': c[0], 'open': float(c[1]), 'high': float(c[2]), 'low': float(c[3]), 'close': float(c[4]), 'volume': float(c[5])})
        current_start = data[-1][0] + 1
        time.sleep(0.05)
    return all_candles

def calculate_atr(candles, idx, period=14):
    start = max(1, idx - period + 1)
    trs = []
    for i in range(start, idx + 1):
        h, l, pc = candles[i]['high'], candles[i]['low'], candles[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return np.mean(trs) if trs else 50

def get_signal(candles, i, lookback=20, min_wick=2.0, min_vol=1.5):
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
    
    has_wick = wick_ratio >= min_wick
    has_vol = vol_ratio >= min_vol
    has_vel = vel_exhaust
    has_z = abs(z) >= 1.5
    has_rsi = rsi <= 30 or rsi >= 70
    
    confirms = sum([has_wick, has_vol, has_vel, has_z, has_rsi])
    direction = None
    if has_wick: direction = "LONG" if wick_dir == "DOWN" else "SHORT"
    elif has_z: direction = "SHORT" if z > 0 else "LONG"
    elif has_rsi: direction = "LONG" if rsi <= 30 else "SHORT"
    
    if direction:
        return {'direction': direction, 'confirms': confirms, 'has_wick': has_wick, 'has_vol': has_vol, 'high': c['high'], 'low': c['low'], 'close': c['close'], 'candle_time': c['time']}
    return None

def run_grid():
    print("Fetching 180 days of 30m data...")
    candles_30m = fetch_binance_candles("BTCUSDT", "30m", 180)
    print("Fetching 180 days of 5m data...")
    candles_5m = fetch_binance_candles("BTCUSDT", "5m", 180)
    
    configs = []
    for stop_mult in [0.5, 0.75, 1.0, 1.25]:
        for rr in [1.5, 2.0]:
            for min_conf in [2, 3]:
                for req_wick in [False, True]:
                    for req_vol in [False, True]:
                        configs.append((stop_mult, rr, min_conf, req_wick, req_vol))
                        
    print(f"Testing {len(configs)} configurations...")
    
    results = []
    
    # Pre-calculate signals to save time
    all_signals = {}
    for i in range(20, len(candles_30m)):
        sig = get_signal(candles_30m, i)
        if sig:
            all_signals[i] = {**sig, 'atr': calculate_atr(candles_30m, i)}

    for stop_mult, rr, min_conf, req_wick, req_vol in configs:
        wins, losses, unresolved = 0, 0, 0
        last_entry_time = 0
        
        for i, sig in all_signals.items():
            if sig['candle_time'] <= last_entry_time: continue
            if sig['confirms'] < min_conf: continue
            if req_wick and not sig['has_wick']: continue
            if req_vol and not sig['has_vol']: continue
            
            entry = sig['close']
            atr = sig['atr']
            direction = sig['direction']
            
            if direction == "LONG": sl_dist = abs(entry - sig['low']) + (atr * stop_mult)
            else: sl_dist = abs(entry - sig['high']) + (atr * stop_mult)
                
            sl_dist = max(sl_dist, 10)
            tp_dist = sl_dist * rr
            
            if direction == "LONG": tp_price, sl_price = entry + tp_dist, entry - sl_dist
            else: tp_price, sl_price = entry - tp_dist, entry + sl_dist
                
            resolved = False
            start_idx = None
            for j, mc in enumerate(candles_5m):
                if mc['time'] > sig['candle_time']:
                    start_idx = j
                    break
                    
            if start_idx is not None:
                for j in range(start_idx, min(start_idx + 1000, len(candles_5m))):
                    mc = candles_5m[j]
                    if direction == "LONG":
                        if mc['low'] <= sl_price: losses += 1; resolved = True; break
                        if mc['high'] >= tp_price: wins += 1; resolved = True; break
                    else:
                        if mc['high'] >= sl_price: losses += 1; resolved = True; break
                        if mc['low'] <= tp_price: wins += 1; resolved = True; break
                            
            if not resolved: unresolved += 1
            last_entry_time = sig['candle_time']

        tot = wins + losses
        if tot > 50:
            wr = wins / tot * 100
            results.append({
                'sm': stop_mult, 'rr': rr, 'mc': min_conf, 'rw': req_wick, 'rv': req_vol,
                'w': wins, 'l': losses, 'wr': wr, 'tot': tot
            })

    results.sort(key=lambda x: x['wr'], reverse=True)
    
    print("\n" + "="*90)
    print(" GEMINI OPTIMIZER TOP RESULTS (6 MONTHS)")
    print("="*90)
    print(f"{'ATR':<5} | {'RR':<4} | {'Conf':<4} | {'Wick':<5} | {'Vol':<5} | {'W':<5} | {'L':<5} | {'WR%':<6}")
    print("-" * 90)
    for r in results[:20]:
        print(f"{r['sm']:<5} | {r['rr']:<4} | {r['mc']:<4} | {str(r['rw']):<5} | {str(r['rv']):<5} | {r['w']:<5} | {r['l']:<5} | {r['wr']:.1f}%")

run_grid()
