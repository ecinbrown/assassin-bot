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

cfg_path = r"c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy\nogale_86pct_high_confluence_config.json"
engine = HybridSignalEngine(config_path=cfg_path)
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
                if (s, i) in seen: continue
                seen.add((s, i))
                f_idx = i + tf
                if f_idx < total_len:
                    ep = tf_candle.close
                    xp = float(raw_1m[s][f_idx][4])
                    won = (xp > ep) if sig['action'].lower() == 'call' else (xp < ep)
                    dt_str = datetime.datetime.fromtimestamp(tf_candle.timestamp, tz=datetime.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
                    trades.append({'dt': dt_str, 'symbol': s, 'tf': tf, 'action': sig['action'], 'entry': ep, 'exit': xp, 'won': won, 'desc': sig['setup'].desc})

print("\n" + "="*80)
print(f"EXACT 24-HOUR TRADE LOG ({len(trades)} trades):")
print("="*80)
for t in trades:
    res = 'WIN ✅' if t['won'] else 'LOSS ❌'
    print(f"{t['dt']} | {t['symbol']:<7} | {t['tf']:>2}m | {t['action']:<4} | Entry: {t['entry']:.4f} -> Exit: {t['exit']:.4f} | {res} | {t['desc']}")
