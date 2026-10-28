import json, os, sys, time, urllib.request

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"c:\Users\DELL\Documents\anti web\assassin-bot")
from assassin_strategy.hybrid_engine import HybridSignalEngine
from assassin_strategy.candle_utils import Candle
from run_24h_replay import fetch_recent_klines, fetch_htf_klines

symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
print("Loading candles...", flush=True)
raw_1m = {s: fetch_recent_klines(s, 1500) for s in symbols}

htf_data = {}
htf_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
for s in symbols:
    for iv_str, tf_min in htf_map.items():
        htf_data[(s, tf_min)] = fetch_htf_klines(s, iv_str, 200)

configs = [
    "walk_forward_validated_config.json",
    "nogale_89pct_ultra_elite_config.json",
    "nogale_86pct_high_confluence_config.json"
]

for cfg_name in configs:
    cfg_path = os.path.join(r"c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy", cfg_name)
    engine = HybridSignalEngine(config_path=cfg_path)
    
    # Warmup 200 candles
    for s in symbols:
        for k in raw_1m[s][:200]:
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
            engine.aggregator.update_1m_candle(s, c)
        for iv_str, tf_min in htf_map.items():
            h_data = htf_data[(s, tf_min)]
            candles = [Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0) for k in h_data]
            engine.aggregator.history[(s, tf_min)] = candles[-200:]
            
    # Replay
    trades = []
    seen = set()
    total_len = len(raw_1m["BTCUSDT"])
    for i in range(200, total_len):
        for s in symbols:
            k = raw_1m[s][i]
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
            closed_tfs = engine.aggregator.update_1m_candle(s, c)
            for tf, tf_candle in closed_tfs:
                sigs = engine.evaluate_setups(s, tf, tf_candle)
                for sig in sigs:
                    # Deduplicate 1 per pair per bar
                    key = (s, i)
                    if key in seen: continue
                    seen.add(key)
                    
                    entry_p = tf_candle.close
                    future_idx = i + tf
                    if future_idx < total_len:
                        exit_p = float(raw_1m[s][future_idx][4])
                        won = (exit_p > entry_p) if sig["action"].lower() == "call" else (exit_p < entry_p)
                        trades.append({"symbol": s, "won": won, "tf": tf, "action": sig["action"], "entry": entry_p, "exit": exit_p, "desc": sig["setup"].desc})
                        
    wins = sum(1 for t in trades if t["won"])
    total = len(trades)
    wr = (wins / total * 100.0) if total > 0 else 0.0
    print(f"\n{'='*60}")
    print(f"CONFIG: {cfg_name} ({len(engine.setups)} setups)")
    print(f"  Total Trades (24h): {total}")
    print(f"  Wins: {wins} | Losses: {total - wins} | WR: {wr:.1f}%")
    print(f"  Pair Breakdown:")
    for sym in symbols:
        st = [t for t in trades if t["symbol"] == sym]
        if st:
            sw = sum(1 for t in st if t["won"])
            print(f"    {sym}: {len(st)} trades | {sw}W-{len(st)-sw}L ({sw/len(st)*100:.1f}%)")
