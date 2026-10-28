import asyncio, os, sys, time
sys.path.insert(0, os.path.abspath('assassin-bot'))
from assassin_strategy.hybrid_engine import HybridSignalEngine
from assassin_strategy.candle_utils import Candle
import urllib.request, json

cfg_path = os.path.join(os.path.dirname(__file__), "assassin_strategy", "oos_85pct_30tpd_config.json")
engine = HybridSignalEngine(config_path=cfg_path)
print(f"Engine initialized with {len(engine.setups)} setups across timeframes: {sorted(list(set(s.tf for s in engine.setups)))}")

symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']

total_sigs = 0
for sym in symbols:
    url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1m&limit=300"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    candles_data = json.loads(urllib.request.urlopen(req, timeout=10).read())
    candles = [
        Candle(
            timestamp=float(k[0])/1000.0,
            open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
            volume=float(k[5]), trades=float(k[8]) if len(k) > 8 else 1.0
        )
        for k in candles_data
    ]
    # Feed first 200 as warmup
    for c in candles[:-60]:
        engine.aggregator.update_1m_candle(sym, c)
    
    # Simulate last 60 minutes
    signals_fired = []
    for c in candles[-60:]:
        closed = engine.aggregator.update_1m_candle(sym, c)
        for tf, tf_c in closed:
            sigs = engine.evaluate_setups(sym, tf, tf_c)
            if sigs:
                signals_fired.extend(sigs)
    total_sigs += len(signals_fired)
    print(f"{sym}: {len(signals_fired)} signals in last 60m")
    for s in signals_fired[:3]:
        wr = getattr(s['setup'], 'wr', 0.0)
        action = s['action']
        tf = s['setup'].tf
        trig = s['trigger']
        print(f"   -> {action} on {tf}m | {trig} | WR: {wr:.1f}%")

print(f"\nTOTAL SIGNALS across 5 pairs in last 60m: {total_sigs}")
