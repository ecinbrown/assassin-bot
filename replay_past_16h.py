import urllib.request, json, time, sys
import pandas as pd
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
from assassin_strategy import HybridSignalEngine, Candle

PAIRS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
engine = HybridSignalEngine(r"c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy\strictly_no_gale_verified_config.json")
print(f"Loaded {len(engine.setups)} setups.")

# Fetch past 1000 1m candles for each pair from Binance REST API (16.6 hours)
candles_by_pair = {}
for p in PAIRS:
    url = f"https://api.binance.com/api/v3/klines?symbol={p}&interval=1m&limit=1000"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            candles_by_pair[p] = data
            t_start = time.strftime('%Y-%m-%d %H:%M', time.gmtime(data[0][0]/1000))
            t_end = time.strftime('%Y-%m-%d %H:%M', time.gmtime(data[-1][0]/1000))
            print(f"Fetched {len(data)} candles for {p}: {t_start} to {t_end} UTC")
    except Exception as e:
        print(f"Error fetching {p}: {e}")

# Warm up aggregator with first 200 candles
for p in PAIRS:
    for k in candles_by_pair[p][:200]:
        c = Candle(
            timestamp=float(k[0]) / 1000.0,
            open=float(k[1]), high=float(k[2]), low=float(k[3]),
            close=float(k[4]), volume=float(k[5]), trades=float(k[8])
        )
        engine.aggregator.update_1m_candle(p, c)

signals = []
for idx in range(200, 1000):
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
                signals.append({
                    'time_utc': time.strftime('%Y-%m-%d %H:%M', time.gmtime(c.timestamp)),
                    'pair': p, 'tf': tf, 'action': s['action'],
                    'trigger': s['trigger'],
                    'setup': s['setup'].desc
                })

print(f"\n==================================================")
print(f"REPLAY OF PAST 13.3 HOURS (800 minutes): {len(signals)} TOTAL SIGNALS FIRED")
print(f"==================================================")
for s in signals:
    print(f"[{s['time_utc']} UTC] {s['pair']} {s['action'].upper()} ({s['tf']}m) | {s['setup']}")
