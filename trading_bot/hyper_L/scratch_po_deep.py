"""
DEEP TICK VELOCITY OPTIMIZER
=============================
Searching for >90% edge on PocketOption OTC using terminal velocity.
We test:
1. Reversal on terminal exhaustion (last N seconds move extremely fast).
2. Continuation on breakout momentum.
"""
import sqlite3
import pandas as pd
import numpy as np

def find_90_edge():
    conn = sqlite3.connect("trading_data.db")
    df = pd.read_sql_query("SELECT timestamp, price FROM ticks WHERE symbol='AEDCNY_otc' AND timestamp > 0 ORDER BY timestamp ASC", conn)
    conn.close()
    
    df['minute_ts'] = (df['timestamp'] // 60) * 60
    minutes = df.groupby('minute_ts')
    
    trades = []
    
    for minute, ticks in minutes:
        if len(ticks) < 15: continue
        ticks = ticks.sort_values('timestamp')
        
        close_p = ticks['price'].iloc[-1]
        open_p = ticks['price'].iloc[0]
        
        # Velocity in last 5 seconds
        end_time = ticks['timestamp'].iloc[-1]
        final_ticks = ticks[ticks['timestamp'] >= end_time - 5.0]
        if len(final_ticks) < 5: continue
        
        t5_open = final_ticks['price'].iloc[0]
        t5_close = final_ticks['price'].iloc[-1]
        t5_move = t5_close - t5_open
        
        # Velocity in full minute
        m_move = close_p - open_p
        
        # Tick count
        tick_count = len(ticks)
        t5_tick_count = len(final_ticks)
        
        trades.append({
            'minute': minute,
            'close': close_p,
            't5_move': t5_move,
            't5_move_abs': abs(t5_move),
            'm_move': m_move,
            'm_move_abs': abs(m_move),
            'tick_count': tick_count,
            't5_ticks': t5_tick_count
        })
        
    res_df = pd.DataFrame(trades)
    res_df = res_df.sort_values('minute').reset_index(drop=True)
    res_df['next_close'] = res_df['close'].shift(-1)
    res_df['next_dir'] = np.where(res_df['next_close'] > res_df['close'], 1, 0)
    
    # Calculate statistics
    m_move_std = res_df['m_move_abs'].std()
    t5_move_std = res_df['t5_move_abs'].std()
    
    print(f"Total minutes analyzed: {len(res_df)}")
    
    results = []
    
    # Grid search for anomalies
    for m_mult in [0.5, 1.0, 1.5, 2.0, 2.5]:
        for t5_mult in [0.5, 1.0, 1.5, 2.0, 2.5]:
            
            m_thresh = res_df['m_move_abs'].mean() + (m_mult * m_move_std)
            t5_thresh = res_df['t5_move_abs'].mean() + (t5_mult * t5_move_std)
            
            # SCENARIO 1: Terminal Exhaustion (Reversal)
            # Full minute was strong, AND last 5 seconds was extremely strong in same direction
            up_exh = (res_df['m_move'] > m_thresh) & (res_df['t5_move'] > t5_thresh)
            down_exh = (res_df['m_move'] < -m_thresh) & (res_df['t5_move'] < -t5_thresh)
            
            # Bet Reversal
            wins_rev = len(res_df[up_exh]) - res_df[up_exh]['next_dir'].sum() + res_df[down_exh]['next_dir'].sum()
            tot_rev = len(res_df[up_exh]) + len(res_df[down_exh])
            if tot_rev > 5:
                results.append((f"Reversal (M{m_mult} T{t5_mult})", tot_rev, wins_rev/tot_rev*100))
                
            # SCENARIO 2: Terminal Continuation
            # Bet Continuation
            wins_cont = res_df[up_exh]['next_dir'].sum() + len(res_df[down_exh]) - res_df[down_exh]['next_dir'].sum()
            if tot_rev > 5:
                results.append((f"Continuation (M{m_mult} T{t5_mult})", tot_rev, wins_cont/tot_rev*100))
                
            # SCENARIO 3: Snapback trap
            # Minute was flat or small, but last 5 seconds exploded
            flat_m = res_df['m_move_abs'] < res_df['m_move_abs'].mean()
            up_trap = flat_m & (res_df['t5_move'] > t5_thresh)
            down_trap = flat_m & (res_df['t5_move'] < -t5_thresh)
            
            tot_trap = len(res_df[up_trap]) + len(res_df[down_trap])
            wins_trap_rev = len(res_df[up_trap]) - res_df[up_trap]['next_dir'].sum() + res_df[down_trap]['next_dir'].sum()
            if tot_trap > 5:
                results.append((f"Trap Reversal (T{t5_mult})", tot_trap, wins_trap_rev/tot_trap*100))
                
    print("\nRESULTS:")
    for r in sorted(results, key=lambda x: x[2], reverse=True)[:15]:
        print(f"{r[0]:<30} | {r[1]:<6} | {r[2]:.1f}%")

if __name__ == "__main__":
    find_90_edge()
