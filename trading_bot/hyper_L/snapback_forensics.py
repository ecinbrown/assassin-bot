"""
Hyperliquid BTC Snapback Forensics
====================================
The SAME nuclear forensics framework we used on PocketOption OTC data,
but adapted for REAL market data from Hyperliquid BTC perpetual futures.

Instead of hunting for PRNG artifacts, we hunt for MICROSTRUCTURE anomalies:
- Liquidity sweeps (stop-loss hunts)
- Volatility spikes that revert
- Rapid price dislocations that snap back

For scalping on perps, we don't need a timer. We need:
1. Entry signal (the anomaly)
2. Expected snapback magnitude (take-profit in pips)
3. Max adverse excursion (stop-loss in pips)
4. Risk:Reward ratio >= 1:2
"""

import csv
import os
import sys
import numpy as np
from collections import defaultdict
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(__file__), "btc_1m_candles.csv")

def load_data():
    """Load the BTC 1m candle CSV."""
    rows = []
    with open(DATA_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'timestamp': int(row['timestamp']),
                'datetime': row['datetime'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
    return rows

def compute_signals(candles, lookback=20):
    """
    For each candle, compute:
    - velocity: close-to-close change 
    - z_score: how abnormal the velocity is vs the last N candles
    - range_pips: high-low range in dollars
    - direction_flips: how many times direction changed in last N candles
    - body_ratio: abs(close-open) / (high-low) — how much of the candle is "body" vs wick
    """
    signals = []
    
    for i in range(lookback, len(candles)):
        window = candles[i - lookback:i]
        current = candles[i]
        
        velocities = [window[j]['close'] - window[j-1]['close'] for j in range(1, len(window))]
        current_vel = current['close'] - candles[i-1]['close']
        
        mean_v = np.mean(velocities)
        std_v = np.std(velocities)
        
        if std_v == 0:
            continue
            
        z_score = (current_vel - mean_v) / std_v
        
        # Direction flips
        flips = 0
        for j in range(1, len(velocities)):
            if (velocities[j] > 0) != (velocities[j-1] > 0):
                flips += 1
        
        # Range in dollars
        range_usd = current['high'] - current['low']
        
        # Body ratio (how "solid" is the candle — 1.0 = pure body, 0.0 = pure wick)
        if range_usd > 0:
            body_ratio = abs(current['close'] - current['open']) / range_usd
        else:
            body_ratio = 0
            
        # Volume spike (relative to window average)
        avg_vol = np.mean([c['volume'] for c in window])
        vol_ratio = current['volume'] / avg_vol if avg_vol > 0 else 1.0
        
        signals.append({
            'index': i,
            'datetime': current['datetime'],
            'close': current['close'],
            'velocity': current_vel,
            'z_score': z_score,
            'flips': flips,
            'range_usd': range_usd,
            'body_ratio': body_ratio,
            'vol_ratio': vol_ratio,
        })
    
    return signals

def backtest_snapback(candles, signals, 
                       z_threshold=2.5,
                       max_flips=5,
                       min_vol_ratio=1.5,
                       tp_usd=50.0,
                       sl_usd=25.0,
                       max_hold_candles=10):
    """
    Backtest the snapback strategy on real BTC data.
    
    Entry: When z_score exceeds threshold (spike detected), enter AGAINST the spike.
    Exit: Either hit take-profit, stop-loss, or max hold time.
    
    Returns list of trade results.
    """
    trades = []
    in_trade = False
    
    for sig in signals:
        if in_trade:
            continue
            
        # Filter conditions
        if abs(sig['z_score']) < z_threshold:
            continue
        if sig['flips'] > max_flips:
            continue
        if sig['vol_ratio'] < min_vol_ratio:
            continue
            
        # Entry: trade AGAINST the spike
        entry_idx = sig['index']
        entry_price = sig['close']
        direction = "SHORT" if sig['z_score'] > 0 else "LONG"
        
        # Simulate forward
        exit_price = None
        exit_reason = None
        
        for j in range(1, max_hold_candles + 1):
            if entry_idx + j >= len(candles):
                break
                
            future = candles[entry_idx + j]
            
            if direction == "LONG":
                # Check TP (price went up)
                if future['high'] - entry_price >= tp_usd:
                    exit_price = entry_price + tp_usd
                    exit_reason = "TP"
                    break
                # Check SL (price went down more)
                if entry_price - future['low'] >= sl_usd:
                    exit_price = entry_price - sl_usd
                    exit_reason = "SL"
                    break
            else:  # SHORT
                # Check TP (price went down)
                if entry_price - future['low'] >= tp_usd:
                    exit_price = entry_price - tp_usd
                    exit_reason = "TP"
                    break
                # Check SL (price went up more)
                if future['high'] - entry_price >= sl_usd:
                    exit_price = entry_price + sl_usd
                    exit_reason = "SL"
                    break
        
        if exit_price is None:
            # Max hold reached, close at last candle's close
            last_idx = min(entry_idx + max_hold_candles, len(candles) - 1)
            exit_price = candles[last_idx]['close']
            exit_reason = "TIMEOUT"
        
        # Calculate PnL
        if direction == "LONG":
            pnl = exit_price - entry_price
        else:
            pnl = entry_price - exit_price
            
        trades.append({
            'datetime': sig['datetime'],
            'direction': direction,
            'entry': entry_price,
            'exit': exit_price,
            'pnl_usd': pnl,
            'exit_reason': exit_reason,
            'z_score': sig['z_score'],
            'vol_ratio': sig['vol_ratio'],
            'flips': sig['flips'],
        })
        
        in_trade = True
        # Simple cooldown: skip next few candles
        # (handled by the in_trade flag + we reset after processing)
        in_trade = False  # Allow next trade (no overlap since we simulate forward)
    
    return trades

def run_grid_search(candles, signals):
    """Brute-force parameter sweep to find the optimal snapback filters for BTC."""
    
    print("\n" + "=" * 70)
    print("  NUCLEAR GRID SEARCH: BTC SNAPBACK PARAMETERS")
    print("=" * 70)
    
    best_results = []
    
    z_thresholds = [2.0, 2.5, 3.0, 3.5, 4.0]
    max_flips_list = [3, 5, 8, 12]
    vol_ratios = [1.0, 1.5, 2.0, 3.0]
    tp_levels = [30, 50, 75, 100, 150]   # USD take-profit
    sl_levels = [15, 25, 40, 50]          # USD stop-loss
    hold_times = [5, 10, 15, 20]          # candles (minutes)
    
    total_combos = len(z_thresholds) * len(max_flips_list) * len(vol_ratios) * len(tp_levels) * len(sl_levels) * len(hold_times)
    print(f"  Testing {total_combos} parameter combinations...\n")
    
    tested = 0
    
    for z in z_thresholds:
        for mf in max_flips_list:
            for vr in vol_ratios:
                for tp in tp_levels:
                    for sl in sl_levels:
                        for ht in hold_times:
                            trades = backtest_snapback(candles, signals, 
                                                       z_threshold=z, 
                                                       max_flips=mf, 
                                                       min_vol_ratio=vr,
                                                       tp_usd=tp, 
                                                       sl_usd=sl, 
                                                       max_hold_candles=ht)
                            
                            tested += 1
                            if tested % 500 == 0:
                                print(f"  Progress: {tested}/{total_combos} ({100*tested/total_combos:.1f}%)")
                            
                            if len(trades) < 10:
                                continue
                                
                            wins = [t for t in trades if t['pnl_usd'] > 0]
                            losses = [t for t in trades if t['pnl_usd'] <= 0]
                            win_rate = len(wins) / len(trades) * 100
                            total_pnl = sum(t['pnl_usd'] for t in trades)
                            avg_win = np.mean([t['pnl_usd'] for t in wins]) if wins else 0
                            avg_loss = np.mean([abs(t['pnl_usd']) for t in losses]) if losses else 1
                            rr_ratio = avg_win / avg_loss if avg_loss > 0 else 999
                            
                            # We want: decent win rate + good R:R + enough trades
                            score = (win_rate / 100) * rr_ratio * len(trades)
                            
                            best_results.append({
                                'z': z, 'mf': mf, 'vr': vr,
                                'tp': tp, 'sl': sl, 'ht': ht,
                                'trades': len(trades),
                                'win_rate': win_rate,
                                'total_pnl': total_pnl,
                                'avg_win': avg_win,
                                'avg_loss': avg_loss,
                                'rr_ratio': rr_ratio,
                                'score': score,
                            })
    
    # Sort by composite score
    best_results.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n{'='*70}")
    print(f"  TOP 15 PARAMETER COMBINATIONS")
    print(f"{'='*70}\n")
    
    print(f"{'Rank':<5} {'Z':>4} {'Flips':>6} {'VolR':>5} {'TP$':>5} {'SL$':>5} {'Hold':>5} {'Trades':>7} {'WR%':>6} {'R:R':>5} {'PnL$':>10} {'Score':>8}")
    print("-" * 85)
    
    for i, r in enumerate(best_results[:15]):
        print(f"{i+1:<5} {r['z']:>4.1f} {r['mf']:>6} {r['vr']:>5.1f} {r['tp']:>5} {r['sl']:>5} {r['ht']:>5} {r['trades']:>7} {r['win_rate']:>5.1f}% {r['rr_ratio']:>5.2f} ${r['total_pnl']:>9,.0f} {r['score']:>8.1f}")
    
    if best_results:
        best = best_results[0]
        print(f"\n🏆 BEST COMBO: Z>{best['z']} | Flips<{best['mf']} | VolRatio>{best['vr']} | TP=${best['tp']} | SL=${best['sl']} | Hold<{best['ht']}min")
        print(f"   → {best['trades']} trades | {best['win_rate']:.1f}% WR | {best['rr_ratio']:.2f} R:R | ${best['total_pnl']:,.0f} total PnL")
    
    return best_results

if __name__ == "__main__":
    print("=" * 60)
    print("  HYPERLIQUID BTC SNAPBACK FORENSICS")
    print("  Real Market Data | Microstructure Analysis")
    print("=" * 60)
    
    if not os.path.exists(DATA_FILE):
        print(f"\n❌ Data file not found: {DATA_FILE}")
        print(f"   Run fetch_btc_ticks.py first!")
        sys.exit(1)
    
    print(f"\n📂 Loading data from {DATA_FILE}...")
    candles = load_data()
    print(f"   Loaded {len(candles)} candles")
    print(f"   Range: {candles[0]['datetime']} → {candles[-1]['datetime']}")
    print(f"   Price: ${candles[0]['close']:,.2f} → ${candles[-1]['close']:,.2f}")
    
    print(f"\n🔬 Computing signals (lookback=20)...")
    signals = compute_signals(candles, lookback=20)
    print(f"   Generated {len(signals)} signal points")
    
    # High z-score events
    extreme_events = [s for s in signals if abs(s['z_score']) > 3.0]
    print(f"   Extreme events (|Z| > 3.0): {len(extreme_events)}")
    
    # Run grid search
    results = run_grid_search(candles, signals)
    
    # Save results
    results_file = os.path.join(os.path.dirname(__file__), "grid_search_results.csv")
    with open(results_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys() if results else [])
        writer.writeheader()
        writer.writerows(results[:100])  # Save top 100
    
    print(f"\n💾 Top 100 results saved to {results_file}")
