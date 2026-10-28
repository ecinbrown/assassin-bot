import asyncio
import json
import os
import sys
import time
import urllib.request
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, os.path.dirname(__file__))
from assassin_strategy.hybrid_engine import HybridSignalEngine
from assassin_strategy.candle_utils import Candle

def fetch_binance_candles(symbol, interval="1m", limit=1000):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())

async def main():
    cfg_path = os.path.join(os.path.dirname(__file__), "assassin_strategy", "oos_85pct_30tpd_config.json")
    engine = HybridSignalEngine(config_path=cfg_path)
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    
    print("Fetching 1000 1m candles (~16.6 hours) for all 5 pairs...")
    raw = {}
    for s in symbols:
        raw[s] = fetch_binance_candles(s, "1m", 1000)
    
    start_ts = raw["BTCUSDT"][0][0] / 1000.0
    end_ts = raw["BTCUSDT"][-1][0] / 1000.0
    print(f"Time range: {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(start_ts))} to {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(end_ts))}")

    # Use first 200 candles to warm up
    for s in symbols:
        for k in raw[s][:200]:
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
            engine.aggregator.update_1m_candle(s, c)
            
    # Also seed HTF history directly as main.py does
    htf_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
    for s in symbols:
        for iv_str, tf_min in htf_map.items():
            h_data = fetch_binance_candles(s, iv_str, 200)
            candles = [
                Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
                for k in h_data
            ]
            engine.aggregator.history[(s, tf_min)] = candles[-200:]

    # Now replay remaining 800 candles (~13.3 hours)
    signals = []
    trade_outcomes = []
    
    for i in range(200, 1000):
        for s in symbols:
            k = raw[s][i]
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
            closed_tfs = engine.aggregator.update_1m_candle(s, c)
            for tf, tf_candle in closed_tfs:
                sigs = engine.evaluate_setups(s, tf, tf_candle)
                for sig in sigs:
                    # Check future outcome if possible
                    entry_p = tf_candle.close
                    expiry_bars = sig["setup"].params.get("expiry_bars", 1)
                    future_idx = i + (tf * expiry_bars)
                    won = None
                    if future_idx < len(raw[s]):
                        exit_p = float(raw[s][future_idx][4]) # close of that candle
                        if sig["action"].lower() == "call":
                            won = exit_p > entry_p
                        else:
                            won = exit_p < entry_p
                    signals.append((c.timestamp, s, tf, sig, won, entry_p))

    print(f"\nTotal signals in past 13.3 hours: {len(signals)}")
    for ts, s, tf, sig, won, ep in signals:
        dt = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(ts))
        w_str = "WIN ✅" if won is True else ("LOSS ❌" if won is False else "PENDING ⏳")
        print(f"  [{dt}] {s} {sig['action'].upper()} on {tf}m | Entry: {ep:.2f} | {w_str} | WR: {sig['confidence']*100:.1f}% | {sig['trigger'][:55]}...")

if __name__ == "__main__":
    asyncio.run(main())
