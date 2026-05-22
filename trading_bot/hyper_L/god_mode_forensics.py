"""
═══════════════════════════════════════════════════════════════
  GOD MODE FORENSICS: Multi-Confirmation Structural Edge
  Stack multiple mathematical confirmations to push accuracy
  while maintaining aggressive Risk:Reward ratios.
═══════════════════════════════════════════════════════════════

The previous single-signal approach:
  - Wick ratio alone → 70% WR but only 1.3:1 R:R
  - Wick ratio alone → 45% WR at 2:1 R:R

This engine STACKS confirmations:
  1. Liquidation Wick (the rubber band)
  2. Volume Spike (institutional activity)  
  3. Velocity Exhaustion (3-candle blow-off)
  4. Mean Reversion Pressure (price far from 20-period mean)
  5. Micro-RSI Extreme (overbought/oversold on 1m)

More confirmations = higher accuracy. The market CANNOT ignore
all 5 signals firing simultaneously.
"""

import csv
import os
import numpy as np

DATA_FILE = os.path.join(os.path.dirname(__file__), "btc_5m_30d.csv")


def load_data():
    rows = []
    with open(DATA_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({
                'datetime': row['datetime'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
    return rows


def compute_all_signals(candles, lookback=20):
    """Compute every possible mathematical signal for each candle."""
    signals = []
    
    for i in range(lookback, len(candles)):
        c = candles[i]
        prev = candles[i - 1]
        
        # === SIGNAL 1: WICK RATIO ===
        body = abs(c['close'] - c['open'])
        if body == 0: body = 0.01
        range_usd = c['high'] - c['low']
        if range_usd == 0: range_usd = 0.01
        
        upper_wick = c['high'] - max(c['open'], c['close'])
        lower_wick = min(c['open'], c['close']) - c['low']
        max_wick = max(upper_wick, lower_wick)
        wick_ratio = max_wick / body
        
        # Direction of the wick rejection
        wick_direction = "DOWN" if lower_wick > upper_wick else "UP"
        
        # === SIGNAL 2: VOLUME SPIKE ===
        vol_window = [candles[j]['volume'] for j in range(i - lookback, i)]
        avg_vol = np.mean(vol_window) if vol_window else 1
        if avg_vol == 0: avg_vol = 0.01
        vol_ratio = c['volume'] / avg_vol
        
        # === SIGNAL 3: VELOCITY EXHAUSTION ===
        # 3 consecutive candles accelerating in the same direction
        vel_1 = c['close'] - prev['close']
        vel_2 = prev['close'] - candles[i - 2]['close']
        vel_3 = candles[i - 2]['close'] - candles[i - 3]['close']
        
        same_direction = (vel_1 * vel_2 > 0) and (vel_2 * vel_3 > 0)
        accelerating = abs(vel_1) > abs(vel_2) > abs(vel_3)
        velocity_exhaustion = same_direction and accelerating
        
        # === SIGNAL 4: MEAN REVERSION PRESSURE ===
        close_window = [candles[j]['close'] for j in range(i - lookback, i)]
        mean_price = np.mean(close_window)
        std_price = np.std(close_window)
        if std_price == 0: std_price = 0.01
        z_score = (c['close'] - mean_price) / std_price
        
        # === SIGNAL 5: MICRO-RSI (14-period) ===
        rsi_period = min(14, i)
        gains = []
        losses = []
        for j in range(i - rsi_period, i):
            delta = candles[j + 1]['close'] - candles[j]['close']
            if delta > 0:
                gains.append(delta)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(delta))
        
        avg_gain = np.mean(gains) if gains else 0
        avg_loss = np.mean(losses) if losses else 0.01
        if avg_loss == 0: avg_loss = 0.01
        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        
        signals.append({
            'index': i,
            'datetime': c['datetime'],
            'close': c['close'],
            'range_usd': range_usd,
            'wick_ratio': wick_ratio,
            'wick_direction': wick_direction,
            'vol_ratio': vol_ratio,
            'velocity_exhaustion': velocity_exhaustion,
            'z_score': z_score,
            'rsi': rsi,
        })
    
    return signals


def backtest_multi_confirm(candles, signals,
                            min_wick_ratio=3.0,
                            min_vol_ratio=1.5,
                            min_range=50,
                            z_threshold=1.5,
                            rsi_extreme=30,
                            require_velocity=False,
                            min_confirmations=3,
                            tp_usd=100,
                            sl_usd=25,
                            hold_candles=15):
    """
    Multi-confirmation backtester.
    Each signal is a 'vote'. We only trade when we have enough votes.
    """
    trades = []
    
    for sig in signals:
        if sig['range_usd'] < min_range:
            continue
        
        # Count confirmations
        confirmations = 0
        direction = None
        
        # VOTE 1: Massive wick rejection
        if sig['wick_ratio'] >= min_wick_ratio:
            confirmations += 1
            # Trade AGAINST the wick (if massive lower wick → LONG)
            direction = "LONG" if sig['wick_direction'] == "DOWN" else "SHORT"
        
        # VOTE 2: Volume spike (institutional activity)
        if sig['vol_ratio'] >= min_vol_ratio:
            confirmations += 1
        
        # VOTE 3: Velocity exhaustion (blow-off top/bottom)
        if sig['velocity_exhaustion']:
            confirmations += 1
        
        # VOTE 4: Z-score extreme (price far from mean)
        if abs(sig['z_score']) >= z_threshold:
            confirmations += 1
            # If no wick direction yet, use z-score
            if direction is None:
                direction = "SHORT" if sig['z_score'] > 0 else "LONG"
        
        # VOTE 5: RSI extreme
        if sig['rsi'] <= rsi_extreme or sig['rsi'] >= (100 - rsi_extreme):
            confirmations += 1
            if direction is None:
                direction = "LONG" if sig['rsi'] <= rsi_extreme else "SHORT"
        
        # Only fire if we have enough confirmations
        if confirmations < min_confirmations or direction is None:
            continue
        
        # Simulate trade
        entry_price = sig['close']
        exit_price = None
        
        for j in range(1, hold_candles + 1):
            if sig['index'] + j >= len(candles):
                break
            future = candles[sig['index'] + j]
            
            if direction == "LONG":
                if future['high'] - entry_price >= tp_usd:
                    exit_price = entry_price + tp_usd
                    break
                if entry_price - future['low'] >= sl_usd:
                    exit_price = entry_price - sl_usd
                    break
            else:  # SHORT
                if entry_price - future['low'] >= tp_usd:
                    exit_price = entry_price - tp_usd
                    break
                if future['high'] - entry_price >= sl_usd:
                    exit_price = entry_price + sl_usd
                    break
        
        if exit_price is None:
            exit_price = candles[min(sig['index'] + hold_candles, len(candles) - 1)]['close']
        
        pnl = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
        trades.append({
            'pnl': pnl,
            'confirmations': confirmations,
            'direction': direction,
            'datetime': sig['datetime'],
        })
    
    return trades


def run_god_mode():
    print("=" * 70)
    print("  GOD MODE: MULTI-CONFIRMATION STRUCTURAL EDGE")
    print("  Stacking 5 signals. Higher accuracy. Higher R:R.")
    print("=" * 70)
    
    candles = load_data()
    print(f"\n  Loaded {len(candles)} candles")
    print(f"  Range: {candles[0]['datetime']} to {candles[-1]['datetime']}")
    
    signals = compute_all_signals(candles)
    print(f"  Computed {len(signals)} signal points\n")
    
    # Grid search: confirmations x TP x SL
    confirmations_list = [2, 3, 4]
    wick_ratios = [2.0, 3.0, 5.0]
    tps = [50, 100, 250, 500, 1000]        # Up to $1000 BTC moves
    sls = [5, 10, 15, 25]                   # Razor-thin stop-losses
    
    results = []
    total = len(confirmations_list) * len(wick_ratios) * len(tps) * len(sls)
    count = 0
    
    for mc in confirmations_list:
        for wr in wick_ratios:
            for tp in tps:
                for sl in sls:
                    count += 1
                    trades = backtest_multi_confirm(
                        candles, signals,
                        min_wick_ratio=wr,
                        min_confirmations=mc,
                        tp_usd=tp,
                        sl_usd=sl,
                    )
                    
                    if len(trades) < 3:
                        continue
                    
                    wins = len([t for t in trades if t['pnl'] > 0])
                    wr_pct = wins / len(trades) * 100
                    total_pnl = sum(t['pnl'] for t in trades)
                    rr = tp / sl
                    
                    # Only keep profitable setups
                    if total_pnl > 0:
                        results.append({
                            'confirms': mc,
                            'wick_r': wr,
                            'tp': tp,
                            'sl': sl,
                            'rr': rr,
                            'trades': len(trades),
                            'wr': wr_pct,
                            'pnl': total_pnl,
                        })
    
    # Sort by R:R ratio (highest first), then by PnL
    results.sort(key=lambda x: (x['rr'], x['pnl']), reverse=True)
    
    print(f"  Tested {total} combinations. Found {len(results)} profitable setups.\n")
    
    # Show ALL results sorted by R:R
    print("=" * 70)
    print("  ALL PROFITABLE SETUPS (Sorted by Risk:Reward Ratio)")
    print("=" * 70)
    print(f"\n{'Conf':>4} {'WickR':>5} {'TP$':>5} {'SL$':>5} | {'R:R':>6} | {'Trades':>6} {'WR%':>6} | {'PnL$':>8}")
    print("-" * 65)
    for r in results[:25]:
        print(f"{r['confirms']:>4} {r['wick_r']:>5.1f} {r['tp']:>5} {r['sl']:>5} | {r['rr']:>5.1f}:1 | {r['trades']:>6} {r['wr']:>5.1f}% | ${r['pnl']:>7.0f}")
    
    # Show the WHALE ZONE: R:R >= 20
    print("\n" + "=" * 70)
    print("  WHALE ZONE: R:R >= 20:1 (The 67:1 Hunt)")
    print("=" * 70)
    
    whales = [r for r in results if r['rr'] >= 20.0]
    whales.sort(key=lambda x: x['pnl'], reverse=True)
    
    if whales:
        print(f"\n{'Conf':>4} {'WickR':>5} {'TP$':>5} {'SL$':>5} | {'R:R':>6} | {'Trades':>6} {'WR%':>6} | {'PnL$':>8}")
        print("-" * 65)
        for w in whales:
            print(f"{w['confirms']:>4} {w['wick_r']:>5.1f} {w['tp']:>5} {w['sl']:>5} | {w['rr']:>5.1f}:1 | {w['trades']:>6} {w['wr']:>5.1f}% | ${w['pnl']:>7.0f}")
    else:
        print("  No profitable setups found at R:R >= 20:1.")
    
    # Show SWEET SPOT: R:R >= 2
    print("\n" + "=" * 70)
    print("  SWEET SPOT: Best PnL WHERE R:R >= 2:1")
    print("=" * 70)
    
    sweet = [r for r in results if r['rr'] >= 2.0]
    sweet.sort(key=lambda x: x['pnl'], reverse=True)
    
    if sweet:
        print(f"\n{'Conf':>4} {'WickR':>5} {'TP$':>5} {'SL$':>5} | {'R:R':>6} | {'Trades':>6} {'WR%':>6} | {'PnL$':>8}")
        print("-" * 65)
        for s in sweet[:15]:
            print(f"{s['confirms']:>4} {s['wick_r']:>5.1f} {s['tp']:>5} {s['sl']:>5} | {s['rr']:>5.1f}:1 | {s['trades']:>6} {s['wr']:>5.1f}% | ${s['pnl']:>7.0f}")


if __name__ == "__main__":
    run_god_mode()
