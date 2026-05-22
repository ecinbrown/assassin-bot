import sys
import math
import requests
from collections import defaultdict
from datetime import datetime, timezone

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
            'o': float(c[1]),
            'h': float(c[2]),
            'l': float(c[3]),
            'c': float(c[4]),
            'v': float(c[5])
        })
    return parsed

def sma(data, i, period, key='c'):
    if i < period: return 0
    return sum(data[j][key] for j in range(i-period, i)) / period

def stddev(data, i, period):
    if i < period: return 0
    mean = sum(data[j]['c'] for j in range(i-period, i)) / period
    variance = sum((data[j]['c'] - mean) ** 2 for j in range(i-period, i)) / period
    return math.sqrt(variance)

def make_vcp_fakeout(vol_mult, stddev_pct):
    def strategy(candles, i):
        # We need historical stddev to check percentile
        # But we only have 800 candles total
        stddev_history = []
        for j in range(max(20, i-200), i+1):
            current_sd = stddev(candles, j, 20)
            if current_sd > 0:
                stddev_history.append(current_sd)
                
        if len(stddev_history) < 20: return None
        
        p_stddev = sorted(stddev_history)[int(stddev_pct * len(stddev_history))]
        if stddev_history[-2] > p_stddev:
            return None
            
        c = candles[i]
        vol_sma_val = sma(candles, i, 20, key='v')
        if vol_sma_val == 0: return None
        
        if c['v'] <= vol_sma_val * vol_mult:
            return None
            
        recent_high = max(candles[j]['h'] for j in range(i-20, i))
        recent_low = min(candles[j]['l'] for j in range(i-20, i))
        
        if c['c'] > recent_high:
            sl_dist = abs(c['c'] - recent_low)
            return ("SHORT", sl_dist)
        elif c['c'] < recent_low:
            sl_dist = abs(recent_high - c['c'])
            return ("LONG", sl_dist)
        return None
    return strategy

def run_strategy(candles, strategy_fn, rr_ratio):
    wins = 0
    losses = 0
    trade_active = False
    is_long = False
    sl_price = 0
    tp_price = 0
    
    for i in range(220, len(candles)):
        c = candles[i]
        
        if trade_active:
            if is_long:
                if c['l'] <= sl_price:
                    losses += 1
                    trade_active = False
                elif c['h'] >= tp_price:
                    wins += 1
                    trade_active = False
            else:
                if c['h'] >= sl_price:
                    losses += 1
                    trade_active = False
                elif c['l'] <= tp_price:
                    wins += 1
                    trade_active = False
            continue
        
        signal = strategy_fn(candles, i)
        if signal is None:
            continue
            
        direction, sl_dist_base = signal
        is_long = (direction == "LONG")
        tp_dist = sl_dist_base * rr_ratio
        
        if is_long:
            sl_price = c['c'] - sl_dist_base
            tp_price = c['c'] + tp_dist
        else:
            sl_price = c['c'] + sl_dist_base
            tp_price = c['c'] - tp_dist
            
        trade_active = True
        
    return wins, losses

def optimize_49h():
    limit = 808
    all_candles = {}
    print("Fetching 49h live data...")
    for coin in TARGET_COINS:
        try:
            parsed = fetch_binance_klines(coin, "5m", limit)
            parsed.sort(key=lambda x: x['time'])
            all_candles[coin] = parsed
        except Exception as e:
            pass

    strategies = {
        "VCP(vol1.5, p10)": make_vcp_fakeout(1.5, 0.10),
        "VCP(vol2.0, p10)": make_vcp_fakeout(2.0, 0.10),
        "VCP(vol1.5, p20)": make_vcp_fakeout(1.5, 0.20),
        "VCP(vol2.0, p20)": make_vcp_fakeout(2.0, 0.20),
        "VCP(vol3.0, p10)": make_vcp_fakeout(3.0, 0.10),
    }
    
    results = defaultdict(lambda: {'wins': 0, 'losses': 0})
    
    print("Running simulations...")
    for coin, candles in all_candles.items():
        for strat_name, strat_fn in strategies.items():
            for rr in [0.5, 1.0, 1.5, 2.0]:
                label = f"{strat_name} | RR: {rr}"
                w, l = run_strategy(candles, strat_fn, rr)
                results[label]['wins'] += w
                results[label]['losses'] += l
                
    final = []
    for label, res in results.items():
        w = res['wins']
        l = res['losses']
        total = w + l
        wr = (w / total * 100) if total > 0 else 0
        final.append({
            'label': label,
            'wins': w,
            'losses': l,
            'total': total,
            'wr': wr
        })
        
    final.sort(key=lambda x: -x['wins'])
    
    print("\nTop Variations by WINS (49h Data):")
    for r in final[:10]:
        print(f"{r['label']:<30} | {r['wins']}W / {r['losses']}L ({r['wr']:.1f}%) | Total: {r['total']}")

if __name__ == '__main__':
    optimize_49h()
