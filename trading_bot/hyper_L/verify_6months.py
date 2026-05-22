"""
═══════════════════════════════════════════════════════════════
  THE ASSASSIN: 6-MONTH ABSOLUTE VERIFICATION
  180 days of real BTC data. The definitive test.
═══════════════════════════════════════════════════════════════
"""
import csv, os
import numpy as np

DATA_FILE = os.path.join(os.path.dirname(__file__), "btc_1h_6months.csv")

def load_data():
    rows = []
    with open(DATA_FILE, 'r') as f:
        for row in csv.DictReader(f):
            rows.append({
                'datetime': row['datetime'],
                'open': float(row['open']),
                'high': float(row['high']),
                'low': float(row['low']),
                'close': float(row['close']),
                'volume': float(row['volume']),
            })
    return rows

def compute_signals(candles, lookback=20):
    signals = []
    for i in range(lookback, len(candles)):
        c = candles[i]
        prev = candles[i-1]
        
        body = abs(c['close'] - c['open'])
        if body == 0: body = 0.01
        rng = c['high'] - c['low']
        if rng == 0: rng = 0.01
        
        upper_wick = c['high'] - max(c['open'], c['close'])
        lower_wick = min(c['open'], c['close']) - c['low']
        max_wick = max(upper_wick, lower_wick)
        wick_ratio = max_wick / body
        wick_dir = "DOWN" if lower_wick > upper_wick else "UP"
        
        vol_window = [candles[j]['volume'] for j in range(i-lookback, i)]
        avg_vol = np.mean(vol_window) if vol_window else 0.01
        if avg_vol == 0: avg_vol = 0.01
        vol_ratio = c['volume'] / avg_vol
        
        close_window = [candles[j]['close'] for j in range(i-lookback, i)]
        mean_p = np.mean(close_window)
        std_p = np.std(close_window)
        if std_p == 0: std_p = 0.01
        z = (c['close'] - mean_p) / std_p
        
        rsi_period = min(14, i)
        gains, losses = [], []
        for j in range(i-rsi_period, i):
            d = candles[j+1]['close'] - candles[j]['close']
            gains.append(max(d, 0))
            losses.append(abs(min(d, 0)))
        avg_g = np.mean(gains) if gains else 0
        avg_l = np.mean(losses) if losses else 0.01
        if avg_l == 0: avg_l = 0.01
        rsi = 100 - (100 / (1 + avg_g/avg_l))
        
        vel1 = c['close'] - prev['close']
        vel2 = prev['close'] - candles[i-2]['close']
        vel3 = candles[i-2]['close'] - candles[i-3]['close']
        vel_exhaust = (vel1*vel2 > 0) and (vel2*vel3 > 0) and (abs(vel1) > abs(vel2) > abs(vel3))
        
        signals.append({
            'index': i, 'datetime': c['datetime'], 'close': c['close'],
            'range': rng, 'wick_ratio': wick_ratio, 'wick_dir': wick_dir,
            'vol_ratio': vol_ratio, 'z': z, 'rsi': rsi, 'vel_exhaust': vel_exhaust
        })
    return signals

def run_backtest(candles, signals, tp, sl, min_confirms=2, min_wick=2.0, min_range=50, hold=15):
    trades = []
    last_trade_idx = -999
    
    for sig in signals:
        if sig['range'] < min_range: continue
        if sig['index'] - last_trade_idx < 3: continue  # Cooldown
        
        confirms = 0
        direction = None
        
        if sig['wick_ratio'] >= min_wick:
            confirms += 1
            direction = "LONG" if sig['wick_dir'] == "DOWN" else "SHORT"
        if sig['vol_ratio'] >= 1.5: confirms += 1
        if sig['vel_exhaust']: confirms += 1
        if abs(sig['z']) >= 1.5:
            confirms += 1
            if not direction: direction = "SHORT" if sig['z'] > 0 else "LONG"
        if sig['rsi'] <= 30 or sig['rsi'] >= 70:
            confirms += 1
            if not direction: direction = "LONG" if sig['rsi'] <= 30 else "SHORT"
        
        if confirms < min_confirms or not direction: continue
        
        entry = sig['close']
        exit_p = None
        for j in range(1, hold+1):
            if sig['index']+j >= len(candles): break
            f = candles[sig['index']+j]
            if direction == "LONG":
                if f['high'] - entry >= tp: exit_p = entry + tp; break
                if entry - f['low'] >= sl: exit_p = entry - sl; break
            else:
                if entry - f['low'] >= tp: exit_p = entry - tp; break
                if f['high'] - entry >= sl: exit_p = entry + sl; break
        
        if exit_p is None:
            exit_p = candles[min(sig['index']+hold, len(candles)-1)]['close']
        
        pnl = (exit_p - entry) if direction == "LONG" else (entry - exit_p)
        trades.append({
            'pnl': pnl, 'confirms': confirms, 'dt': sig['datetime'],
            'direction': direction, 'month': sig['datetime'][:7]
        })
        last_trade_idx = sig['index']
    
    return trades

def main():
    print("=" * 70)
    print("  THE ASSASSIN: 6-MONTH DEFINITIVE VERIFICATION")
    print("  TP=$50 | SL=$5 | R:R=10:1 | 2 Confirmations")
    print("=" * 70)
    
    candles = load_data()
    signals = compute_signals(candles)
    
    print(f"\n  Data: {len(candles)} candles (1h) | 180 days")
    print(f"  Range: {candles[0]['datetime']} to {candles[-1]['datetime']}")
    print(f"  Price: ${candles[0]['close']:,.0f} → ${candles[-1]['close']:,.0f}")
    print(f"  Signals: {len(signals)}")
    
    # THE ASSASSIN: TP=$50, SL=$5
    trades = run_backtest(candles, signals, tp=50, sl=5)
    
    if not trades:
        print("  No trades found!")
        return
    
    wins = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_pnl = sum(t['pnl'] for t in trades)
    wr = len(wins) / len(trades) * 100
    breakeven_wr = (5 / (50 + 5)) * 100
    edge = wr - breakeven_wr
    
    print(f"\n  {'='*55}")
    print(f"  CORE RESULTS")
    print(f"  {'='*55}")
    print(f"  Total Trades:      {len(trades)}")
    print(f"  Wins:              {len(wins)}")
    print(f"  Losses:            {len(losses)}")
    print(f"  Win Rate:          {wr:.1f}%")
    print(f"  Total PnL:         ${total_pnl:,.0f}")
    print(f"  Avg Win:           ${np.mean([t['pnl'] for t in wins]):,.2f}" if wins else "")
    print(f"  Avg Loss:          ${np.mean([t['pnl'] for t in losses]):,.2f}" if losses else "")
    print(f"  Trades/Day:        {len(trades) / 180:.1f}")
    print(f"  Profit/Day:        ${total_pnl / 180:,.0f}")
    print(f"  Breakeven WR:      {breakeven_wr:.1f}%")
    print(f"  EDGE:              +{edge:.1f}%")
    
    # LONG vs SHORT breakdown
    longs = [t for t in trades if t['direction'] == 'LONG']
    shorts = [t for t in trades if t['direction'] == 'SHORT']
    long_wr = len([t for t in longs if t['pnl'] > 0]) / len(longs) * 100 if longs else 0
    short_wr = len([t for t in shorts if t['pnl'] > 0]) / len(shorts) * 100 if shorts else 0
    
    print(f"\n  {'='*55}")
    print(f"  DIRECTIONAL BREAKDOWN")
    print(f"  {'='*55}")
    print(f"  LONG:  {len(longs)} trades | {long_wr:.1f}% WR | ${sum(t['pnl'] for t in longs):,.0f} PnL")
    print(f"  SHORT: {len(shorts)} trades | {short_wr:.1f}% WR | ${sum(t['pnl'] for t in shorts):,.0f} PnL")
    
    # Monthly breakdown
    print(f"\n  {'='*55}")
    print(f"  MONTHLY CONSISTENCY")
    print(f"  {'='*55}")
    
    months = sorted(set(t['month'] for t in trades))
    all_profitable = True
    for month in months:
        mt = [t for t in trades if t['month'] == month]
        mw = len([t for t in mt if t['pnl'] > 0])
        mwr = mw / len(mt) * 100
        mpnl = sum(t['pnl'] for t in mt)
        status = "✅" if mpnl > 0 else "❌"
        if mpnl <= 0: all_profitable = False
        print(f"  {month}: {len(mt):>4} trades | {mwr:>5.1f}% WR | ${mpnl:>8,.0f} | {status}")
    
    # Max drawdown
    print(f"\n  {'='*55}")
    print(f"  RISK ANALYSIS")
    print(f"  {'='*55}")
    
    equity = [0]
    max_streak = 0
    cur_streak = 0
    for t in trades:
        equity.append(equity[-1] + t['pnl'])
        if t['pnl'] <= 0:
            cur_streak += 1
            max_streak = max(max_streak, cur_streak)
        else:
            cur_streak = 0
    
    peak = equity[0]
    max_dd = 0
    for e in equity:
        if e > peak: peak = e
        dd = peak - e
        if dd > max_dd: max_dd = dd
    
    print(f"  Max Losing Streak:   {max_streak} trades")
    print(f"  Max Drawdown:        ${max_dd:,.0f}")
    print(f"  Final Equity:        ${equity[-1]:,.0f}")
    
    # VERDICT
    print(f"\n  {'='*55}")
    if wr > breakeven_wr and total_pnl > 0 and all_profitable:
        print(f"  VERDICT: THE ASSASSIN IS ABSOLUTE.")
        print(f"  {wr:.1f}% WR across {len(trades)} trades over 180 days.")
        print(f"  All {len(months)} months profitable.")
        print(f"  Edge of +{edge:.1f}% — PERMANENT STRUCTURAL ADVANTAGE.")
    elif wr > breakeven_wr and total_pnl > 0:
        print(f"  VERDICT: THE ASSASSIN IS CONFIRMED PROFITABLE.")
        print(f"  {wr:.1f}% WR across {len(trades)} trades.")
        losing_months = [m for m in months if sum(t['pnl'] for t in trades if t['month'] == m) <= 0]
        print(f"  {len(months) - len(losing_months)}/{len(months)} months profitable.")
    else:
        print(f"  VERDICT: EDGE NOT CONFIRMED on 1h timeframe.")
    print(f"  {'='*55}")

if __name__ == "__main__":
    main()
