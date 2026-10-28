import urllib.request, json, time, sys
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
from assassin_strategy import HybridSignalEngine, Candle

PAIRS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
engine = HybridSignalEngine(r"c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy\strictly_no_gale_verified_config.json")
print(f"Loaded {len(engine.setups)} setups across {len(engine.aggregator.timeframes)} timeframes.")

# Fetch past 300 1m candles for each pair from Binance REST API
candles_by_pair = {}
for p in PAIRS:
    url = f"https://api.binance.com/api/v3/klines?symbol={p}&interval=1m&limit=300"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            candles_by_pair[p] = data
            print(f"Fetched {len(data)} candles for {p} (from {time.strftime('%H:%M', time.gmtime(data[0][0]/1000))} to {time.strftime('%H:%M', time.gmtime(data[-1][0]/1000))} UTC)")
    except Exception as e:
        print(f"Error fetching {p}: {e}")

# Warm up aggregator with first 100 candles, then replay the last 200 candles (past 3.3 hours)
for p in PAIRS:
    for k in candles_by_pair[p][:100]:
        c = Candle(
            timestamp=float(k[0]) / 1000.0,
            open=float(k[1]), high=float(k[2]), low=float(k[3]),
            close=float(k[4]), volume=float(k[5]), trades=float(k[8])
        )
        engine.aggregator.update_1m_candle(p, c)

signals_found = []
for idx in range(100, 300):
    for p in PAIRS:
        k = candles_by_pair[p][idx]
        c = Candle(
            timestamp=float(k[0]) / 1000.0,
            open=float(k[1]), high=float(k[2]), low=float(k[3]),
            close=float(k[4]), volume=float(k[5]), trades=float(k[8])
        )
        closed_tfs = engine.aggregator.update_1m_candle(p, c)
        for tf, tf_candle in closed_tfs:
            sigs = engine.evaluate_setups(p, tf, tf_candle)
            for s in sigs:
                signals_found.append({
                    'time_utc': time.strftime('%H:%M:%S', time.gmtime(c.timestamp)),
                    'pair': p, 'tf': tf, 'action': s['action'],
                    'trigger': s['trigger']
                })

print(f"\nReplay of past 200 minutes (3.3 hours): {len(signals_found)} signals fired.")
for s in signals_found:
    print(f"[{s['time_utc']} UTC] {s['pair']} {s['action'].upper()} ({s['tf']}m) | {s['trigger']}")

# Check current indicators on all pairs
print("\n--- CURRENT 5m & 10m MARKET STATE ---")
for p in PAIRS:
    for tf in [5, 10]:
        hist = engine.aggregator.history.get((p, tf), [])
        if len(hist) >= 20:
            closes = np.array([x.close for x in hist])
            ma20 = np.mean(closes[-20:])
            std20 = np.std(closes[-20:], ddof=0)
            bb_z = (closes[-1] - ma20) / max(std20, 1e-8)
            deltas = np.diff(closes[-15:])
            g = np.maximum(deltas, 0)
            l = np.maximum(-deltas, 0)
            rsi7 = 100 - (100 / (1 + (np.mean(g[-7:]) / max(np.mean(l[-7:]), 1e-8))))
            print(f"{p:<8} {tf:2d}m: Close={closes[-1]:<10.2f} | BBz={bb_z:5.2f} | RSI7={rsi7:5.1f}")
