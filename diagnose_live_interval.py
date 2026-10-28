import asyncio
import json
import os
import sys
import time
import urllib.request
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')

# Ensure we import the exact classes from assassin_bot
sys.path.insert(0, os.path.dirname(__file__))
from assassin_strategy.hybrid_engine import HybridSignalEngine, SetupConfig
from assassin_strategy.candle_utils import Candle

def fetch_binance_candles(symbol, interval="1m", limit=300):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

async def main():
    cfg_path = os.path.join(os.path.dirname(__file__), "assassin_strategy", "oos_85pct_30tpd_config.json")
    print(f"Loading config: {cfg_path}")
    engine = HybridSignalEngine(config_path=cfg_path)
    print(f"Loaded {len(engine.setups)} setups across {len(engine.aggregator.timeframes)} timeframes.")

    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    print("Preloading historical warm-up from Binance...")
    await engine.preload_from_binance(symbols, limit=500)

    print("\n" + "="*80)
    print("ANALYZING LIVE REPLAY (Past 180 Minutes / 3 Hours)")
    print("="*80)

    # Now fetch the last 180 1m candles for each symbol and replay them one by one
    # to see if any signals trigger, or what the closest conditions are
    raw_data = {}
    for s in symbols:
        raw_data[s] = fetch_binance_candles(s, interval="1m", limit=180)

    signals_found = []
    close_misses = []

    # Replay chronologically minute by minute across all symbols
    for i in range(180):
        for s in symbols:
            k = raw_data[s][i]
            c = Candle(
                timestamp=float(k[0]) / 1000.0,
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                trades=float(k[8]) if len(k) > 8 else 1.0
            )
            closed_tfs = engine.aggregator.update_1m_candle(s, c)
            for tf, tf_candle in closed_tfs:
                sigs = engine.evaluate_setups(s, tf, tf_candle)
                for sig in sigs:
                    signals_found.append((c.timestamp, s, tf, sig))

    print(f"\nTotal signals triggered in the past 180m: {len(signals_found)}")
    for ts, s, tf, sig in signals_found:
        dt = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(ts))
        print(f"  [{dt}] {s} {sig['action'].upper()} on {tf}m | WR: {sig['confidence']*100:.1f}% | {sig['trigger']}")

    # Now let's inspect the CURRENT market state (most recent candle) for all pairs and top timeframes
    print("\n" + "="*80)
    print("CURRENT LIVE MARKET INDICATOR SNAPSHOT (as of right now):")
    print("="*80)
    for s in symbols:
        for tf in [1, 3, 5, 10, 15]:
            hist = engine.aggregator.history.get((s, tf), [])
            if len(hist) < 20: continue
            closes = np.array([c.close for c in hist])
            ma20 = np.mean(closes[-20:])
            std20 = np.std(closes[-20:])
            bb_z = (closes[-1] - ma20) / max(std20, 1e-8)
            
            # RSI 7
            deltas = np.diff(closes[-37:])
            gains = np.where(deltas > 0, deltas, 0.0)
            losses = np.where(deltas < 0, -deltas, 0.0)
            p = 7
            ag = np.mean(gains[:p])
            al = np.mean(losses[:p])
            for j in range(p, len(deltas)):
                ag = (ag * (p - 1) + gains[j]) / p
                al = (al * (p - 1) + losses[j]) / p
            rsi7 = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
            
            setups_count = len(engine.setups_by_pair_tf.get((s, tf), []))
            if abs(bb_z) > 1.2 or rsi7 < 35 or rsi7 > 65:
                print(f"  {s:7s} {tf:2d}m: Close={closes[-1]:.2f} | BB_Z={bb_z:+.2f}σ | RSI7={rsi7:.1f} | Setups Armed: {setups_count}")

if __name__ == "__main__":
    asyncio.run(main())
