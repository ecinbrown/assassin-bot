import json, os, sys, datetime

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"c:\Users\DELL\Documents\anti web\assassin-bot")
from run_24h_replay import fetch_recent_klines, fetch_htf_klines
from assassin_strategy.hybrid_engine import HybridSignalEngine
from assassin_strategy.candle_utils import Candle

symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
print("Loading candles...", flush=True)
raw_1m = {s: fetch_recent_klines(s, 1500) for s in symbols}
htf_data = {}
for s in symbols:
    for iv, tf in [('15m', 15), ('30m', 30), ('1h', 60), ('4h', 240)]:
        htf_data[(s, tf)] = fetch_htf_klines(s, iv, 200)

configs_to_test = [
    ("High-Confluence (Current)", "nogale_86pct_high_confluence_config.json"),
    ("12 TPD (84%)", "nogale_84pct_12tpd_config.json"),
    ("20 TPD (80%)", "nogale_80pct_20tpd_config.json"),
    ("Walk-Forward (69.7%)", "walk_forward_validated_config.json")
]

strat_dir = r"c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy"

for label, fname in configs_to_test:
    fpath = os.path.join(strat_dir, fname)
    if not os.path.exists(fpath):
        print(f"Skipping {fname} (not found)")
        continue
        
    engine = HybridSignalEngine(config_path=fpath)
    for s in symbols:
        for k in raw_1m[s][:200]:
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), 1.0)
            engine.aggregator.update_1m_candle(s, c)
        for iv, tf in [('15m', 15), ('30m', 30), ('1h', 60), ('4h', 240)]:
            engine.aggregator.history[(s, tf)] = [Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), 1.0) for k in htf_data[(s, tf)]][-200:]

    trades = []
    seen = set()
    total_len = len(raw_1m['BTCUSDT'])
    for i in range(200, total_len):
        for s in symbols:
            k = raw_1m[s][i]
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), 1.0)
            for tf, tf_candle in engine.aggregator.update_1m_candle(s, c):
                for sig in engine.evaluate_setups(s, tf, tf_candle):
                    # Strict 1 trade per pair per bar
                    if (s, i) in seen: continue
                    seen.add((s, i))
                    f_idx = i + tf
                    if f_idx < total_len:
                        ep = tf_candle.close
                        xp = float(raw_1m[s][f_idx][4])
                        won = (xp > ep) if sig['action'].lower() == 'call' else (xp < ep)
                        trades.append({'symbol': s, 'won': won})

    wins = sum(1 for t in trades if t['won'])
    tot = len(trades)
    wr = (wins / tot * 100.0) if tot > 0 else 0.0
    print(f"\n[{label}] ({fname}) - {len(engine.setups)} setups:")
    print(f"  Trades (24h): {tot} (~{tot} TPD) | Wins: {wins} | Losses: {tot - wins} | WR: {wr:.1f}%")
    for s in symbols:
        st = [t for t in trades if t['symbol'] == s]
        if st:
            sw = sum(1 for t in st if t['won'])
            print(f"    {s}: {len(st)} trades | {sw}W-{len(st)-sw}L ({sw/len(st)*100:.1f}%)")
