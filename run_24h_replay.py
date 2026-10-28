import urllib.request, json, time, sys, os
import numpy as np

sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, r"c:\Users\DELL\Documents\anti web\assassin-bot")

from assassin_strategy.hybrid_engine import HybridSignalEngine
from assassin_strategy.candle_utils import Candle

def fetch_recent_klines(symbol, count=1440):
    """Fetch 1440 1m candles (24 hours) from Binance REST API"""
    print(f"Fetching 1m candles for {symbol}...", flush=True)
    url1 = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit=1000"
    req1 = urllib.request.Request(url1, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req1, timeout=10) as r:
        k1 = json.loads(r.read().decode())
    
    first_ts = k1[0][0]
    need_more = count - len(k1)
    if need_more > 0:
        url0 = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1m&limit={need_more}&endTime={first_ts-1}"
        req0 = urllib.request.Request(url0, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req0, timeout=10) as r:
            k0 = json.loads(r.read().decode())
        combined = k0 + k1
    else:
        combined = k1
    return combined

def fetch_htf_klines(symbol, interval, count=250):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={count}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode())

def run_24h_analysis():
    symbols = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
    cfg_path = r"c:\Users\DELL\Documents\anti web\assassin-bot\assassin_strategy\oos_85pct_30tpd_config.json"
    
    print("=" * 70)
    print("PAST 24-HOUR ANALYSIS (BINANCE LIVE FEED REPLAY vs HYBRID ENGINE)")
    print("=" * 70)
    print(f"Loading config: {cfg_path}")
    engine = HybridSignalEngine(config_path=cfg_path)
    print(f"Engine armed with {len(engine.setups)} setups.")
    
    raw_1m = {}
    print("\n[1/3] Fetching past 26+ hours of 1m Binance klines for all 5 pairs...")
    for s in symbols:
        raw_1m[s] = fetch_recent_klines(s, 1600)
        print(f"  - {s}: {len(raw_1m[s])} candles loaded")

    # Time range
    t_start = raw_1m["BTCUSDT"][200][0] / 1000.0  # after 200m warmup
    t_end = raw_1m["BTCUSDT"][-1][0] / 1000.0
    dt_start = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(t_start))
    dt_end = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(t_end))
    hours = (t_end - t_start) / 3600.0
    print(f"\nAnalysis Window: {dt_start} to {dt_end} ({hours:.1f} Hours)")

    # Warmup with first 200 1m candles
    for s in symbols:
        for k in raw_1m[s][:200]:
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
            engine.aggregator.update_1m_candle(s, c)
            
    # HTF warmup matching main.py live bot
    htf_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
    for s in symbols:
        for iv_str, tf_min in htf_map.items():
            h_data = fetch_htf_klines(s, iv_str, 200)
            candles = [
                Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
                for k in h_data
            ]
            engine.aggregator.history[(s, tf_min)] = candles[-200:]

    print("\n[2/3] Simulating live candle-by-candle execution over the past 24 hours...")
    
    # Track trades with NO cooldown (as deployed right now)
    # AND with 3m / 15m pair cooldown to compare
    all_signals = []
    
    total_candles = len(raw_1m["BTCUSDT"])
    for i in range(200, total_candles):
        # Update each symbol
        for s in symbols:
            k = raw_1m[s][i]
            c = Candle(float(k[0])/1000.0, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5]), float(k[8]) if len(k)>8 else 1.0)
            closed_tfs = engine.aggregator.update_1m_candle(s, c)
            for tf, tf_candle in closed_tfs:
                sigs = engine.evaluate_setups(s, tf, tf_candle)
                for sig in sigs:
                    entry_p = tf_candle.close
                    expiry_bars = sig["setup"].params.get("expiry_bars", 1)
                    future_idx = i + (tf * expiry_bars)
                    won = None
                    exit_p = None
                    if future_idx < len(raw_1m[s]):
                        exit_p = float(raw_1m[s][future_idx][4])
                        if sig["action"].lower() == "call":
                            won = (exit_p > entry_p)
                        else:
                            won = (exit_p < entry_p)
                    all_signals.append({
                        "ts": c.timestamp,
                        "time_str": time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(c.timestamp)),
                        "symbol": s,
                        "tf": tf,
                        "action": sig["action"].upper(),
                        "desc": sig["setup"].desc,
                        "expected_wr": sig["confidence"] * 100,
                        "entry": entry_p,
                        "exit": exit_p,
                        "won": won,
                        "expiry_bars": expiry_bars,
                        "candle_idx": i
                    })

    print(f"\n[3/3] Results compiled: Total raw signals fired = {len(all_signals)}")
    
    # 1. RAW SIGNALS (No deduplication, no cooldown - exactly what happened at 9:30 PM with XRP)
    settled_raw = [s for s in all_signals if s["won"] is not None]
    raw_wins = sum(1 for s in settled_raw if s["won"])
    raw_losses = len(settled_raw) - raw_wins
    raw_wr = (raw_wins / len(settled_raw) * 100.0) if settled_raw else 0.0

    # 2. DEDUPLICATED SIGNALS (Only 1 trade per pair per candle - what should happen)
    dedup_signals = []
    seen_candle_sym = set()
    for s in all_signals:
        key = (s["symbol"], s["candle_idx"])
        if key not in seen_candle_sym:
            seen_candle_sym.add(key)
            dedup_signals.append(s)

    settled_dedup = [s for s in dedup_signals if s["won"] is not None]
    dedup_wins = sum(1 for s in settled_dedup if s["won"])
    dedup_losses = len(settled_dedup) - dedup_wins
    dedup_wr = (dedup_wins / len(settled_dedup) * 100.0) if settled_dedup else 0.0

    # Print Detailed Trade List
    print("\n" + "=" * 90)
    print(f"{'TIME (UTC)':<20} | {'PAIR':<8} | {'TF':<3} | {'DIR':<4} | {'ENTRY':<10} | {'EXIT':<10} | {'OUTCOME':<7} | {'STRATEGY'}")
    print("-" * 90)
    for s in settled_raw:
        outcome = "WIN ✅" if s["won"] else "LOSS ❌"
        exit_val = f"{s['exit']:.4f}" if s['exit'] is not None else "N/A"
        print(f"{s['time_str']:<20} | {s['symbol']:<8} | {s['tf']:>2}m | {s['action']:<4} | {s['entry']:<10.4f} | {exit_val:<10} | {outcome:<7} | {s['desc']}")

    print("\n" + "=" * 70)
    print("PAST 24-HOUR SCORECARD SUMMARY")
    print("=" * 70)
    print(f"RAW (CURRENT LIVE SETTING: ZERO COOLDOWN, STACKING TRADES):")
    print(f"  Total Settled: {len(settled_raw)}")
    print(f"  Wins:          {raw_wins}")
    print(f"  Losses:        {raw_losses}")
    print(f"  Win Rate:      {raw_wr:.1f}%")
    print(f"  Net P&L ($1 stake, 85% payout): ${(raw_wins * 0.85 - raw_losses):.2f}")
    print()
    print(f"DEDUPLICATED (1 TRADE PER PAIR PER BAR):")
    print(f"  Total Settled: {len(settled_dedup)}")
    print(f"  Wins:          {dedup_wins}")
    print(f"  Losses:        {dedup_losses}")
    print(f"  Win Rate:      {dedup_wr:.1f}%")
    print(f"  Net P&L ($1 stake, 85% payout): ${(dedup_wins * 0.85 - dedup_losses):.2f}")
    print("=" * 70)

    # Pair by pair breakdown
    print("\nBREAKDOWN BY ASSET:")
    for sym in symbols:
        sym_trades = [s for s in settled_raw if s["symbol"] == sym]
        if sym_trades:
            w = sum(1 for s in sym_trades if s["won"])
            l = len(sym_trades) - w
            wr = w / len(sym_trades) * 100.0
            print(f"  {sym:<8}: {len(sym_trades):>2} trades | {w:>2}W - {l:>2}L | WR: {wr:.1f}%")
        else:
            print(f"  {sym:<8}:  0 trades")

    # Specifically check the 9:30 PM XRP trade
    print("\n" + "=" * 70)
    print("ANALYSIS OF THE TWO XRP TRADES (9:30 PM)")
    print("=" * 70)
    xrp_930 = [s for s in all_signals if s["symbol"] == "XRPUSDT" and "2026-10-20 18:30" in s["time_str"] or ("XRP" in s["symbol"] and abs(s["entry"] - 1.3221) < 0.001)]
    if not xrp_930:
        # Search anywhere between 18:00 and 19:00 UTC (which is 21:00 - 22:00 local UTC+3)
        xrp_930 = [s for s in all_signals if s["symbol"] == "XRPUSDT" and "2026-10-20 18:" in s["time_str"]]
    for x in xrp_930:
        outcome = "WIN ✅" if x["won"] else "LOSS ❌"
        print(f"[{x['time_str']}] {x['desc']} | Entry: {x['entry']} -> Exit: {x['exit']} | {outcome}")

if __name__ == "__main__":
    run_24h_analysis()
