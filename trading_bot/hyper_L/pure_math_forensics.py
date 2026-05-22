"""
Hyperliquid BTC Structural Inefficiency Forensics
===================================================
Breaking textbook rules to hunt for raw mathematical market physics.
We are looking for conditions the market CANNOT ignore:
1. Massive Liquidation Wicks (Orderbook empty, instantly absorbed)
2. Extreme Velocity Blow-offs (Rubber band stretched to breaking point)
3. Micro-Gaps (Rare in crypto, implies extreme slippage)
"""

import csv
import os
import sys
import numpy as np

DATA_FILE = os.path.join(os.path.dirname(__file__), "btc_1m_candles.csv")

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

def compute_inefficiencies(candles, lookback=20):
    signals = []
    for i in range(lookback, len(candles)):
        current = candles[i]
        prev = candles[i-1]
        
        # 1. Wick Ratio (How violent was the rejection?)
        body = abs(current['close'] - current['open'])
        range_usd = current['high'] - current['low']
        
        if body == 0: body = 0.1 # avoid division by zero
        if range_usd == 0: range_usd = 0.1
            
        upper_wick = current['high'] - max(current['open'], current['close'])
        lower_wick = min(current['open'], current['close']) - current['low']
        
        # Is it a massive top wick or bottom wick?
        max_wick = max(upper_wick, lower_wick)
        wick_to_body_ratio = max_wick / body
        
        # 2. Gap (Slippage between minutes)
        gap_usd = current['open'] - prev['close']
        
        # 3. Velocity & Acceleration
        vel_1 = current['close'] - prev['close']
        vel_2 = prev['close'] - candles[i-2]['close']
        vel_3 = candles[i-2]['close'] - candles[i-3]['close']
        
        # Is velocity accelerating? (Blow-off top/bottom)
        is_accelerating = (abs(vel_1) > abs(vel_2) > abs(vel_3)) and (vel_1 * vel_2 > 0) and (vel_2 * vel_3 > 0)
        
        signals.append({
            'index': i,
            'datetime': current['datetime'],
            'close': current['close'],
            'range_usd': range_usd,
            'upper_wick': upper_wick,
            'lower_wick': lower_wick,
            'wick_ratio': wick_to_body_ratio,
            'gap': gap_usd,
            'is_accelerating': is_accelerating,
            'vel_1': vel_1
        })
    return signals

def backtest_inefficiency(candles, signals, 
                          min_wick_ratio=5.0,
                          min_range_usd=100.0,
                          tp_usd=50.0,
                          sl_usd=25.0):
    trades = []
    
    for sig in signals:
        # STRATEGY 1: LIQUIDATION WICK REVERSION
        # Market creates a massive wick (liquidation), we trade AGAINST the wick
        entry_price = sig['close']
        direction = None
        
        # Rule: Range must be big enough to care about
        if sig['range_usd'] < min_range_usd:
            continue
            
        # If massive bottom wick -> Buy the absorption (LONG)
        if sig['lower_wick'] > sig['upper_wick'] and sig['wick_ratio'] > min_wick_ratio:
            direction = "LONG"
        # If massive top wick -> Sell the absorption (SHORT)
        elif sig['upper_wick'] > sig['lower_wick'] and sig['wick_ratio'] > min_wick_ratio:
            direction = "SHORT"
            
        if not direction:
            continue
            
        # Simulate trade (Scalping exactly the next 5-15 candles)
        exit_price = None
        for j in range(1, 15):
            if sig['index'] + j >= len(candles):
                break
            future = candles[sig['index'] + j]
            
            if direction == "LONG":
                if future['high'] - entry_price >= tp_usd:
                    exit_price = entry_price + tp_usd; break
                if entry_price - future['low'] >= sl_usd:
                    exit_price = entry_price - sl_usd; break
            else:
                if entry_price - future['low'] >= tp_usd:
                    exit_price = entry_price - tp_usd; break
                if future['high'] - entry_price >= sl_usd:
                    exit_price = entry_price + sl_usd; break
                    
        if exit_price is None:
            exit_price = candles[min(sig['index'] + 14, len(candles)-1)]['close']
            
        pnl = (exit_price - entry_price) if direction == "LONG" else (entry_price - exit_price)
        trades.append({'pnl': pnl})
        
    return trades

def run_math():
    print("="*60)
    print("  PURE MATH: STRUCTURAL INEFFICIENCY SWEEP")
    print("="*60)
    
    candles = load_data()
    signals = compute_inefficiencies(candles)
    
    # We break textbook rules. We don't care about indicators. 
    # We only care about PURE PIP DISLOCATION limits.
    
    wick_ratios = [2.0, 3.0, 4.0, 5.0]
    ranges = [30, 50, 75]
    
    # To get a 60% win rate, we bring the Take-Profit closer to the entry,
    # and give the trade slightly more room to breathe (Stop-Loss).
    tps = [20, 30, 40, 50]   
    sls = [15, 20, 25, 30]
    
    best = []
    
    for wr in wick_ratios:
        for r in ranges:
            for tp in tps:
                for sl in sls:
                    trades = backtest_inefficiency(candles, signals, wr, r, tp, sl)
                    if len(trades) < 5: continue
                    
                    wins = len([t for t in trades if t['pnl'] > 0])
                    win_rate = wins / len(trades) * 100
                    total_pnl = sum(t['pnl'] for t in trades)
                    
                    # We want to find extreme R:R setups
                    rr_ratio = tp / sl if sl > 0 else 999
                    
                    best.append({
                        'wick_ratio': wr, 'min_range': r, 
                        'tp': tp, 'sl': sl, 'rr': rr_ratio,
                        'trades': len(trades), 
                        'win_rate': win_rate, 
                        'pnl': total_pnl
                    })
                    
    # Sort by Win Rate this time to find the 60%+ setups
    best.sort(key=lambda x: x['win_rate'], reverse=True)
    
    print(f"\n{'WickRat':>7} {'MinRange':>8} {'TP$':>5} {'SL$':>5} | {'R:R':>5} | {'Trades':>6} {'WR%':>6} | {'Total PnL':>10}")
    print("-" * 75)
    
    # Only show profitable setups
    profitable = [b for b in best if b['pnl'] > 0]
    
    for b in profitable[:20]:
        print(f"{b['wick_ratio']:>7.1f} {b['min_range']:>8} {b['tp']:>5} {b['sl']:>5} | {b['rr']:>4.1f}:1 | {b['trades']:>6} {b['win_rate']:>5.1f}% | ${b['pnl']:>9.0f}")

if __name__ == "__main__":
    run_math()
