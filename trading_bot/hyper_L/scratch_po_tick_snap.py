"""
POCKETOPTION TICK-LEVEL EDGE FINDER
===================================
Searching for the >90% "Straight-Line Snap" or "Mega Pip Bomb" on OTC pairs.
We examine the TICK velocity in the final seconds before a 1-minute candle closes
to predict the direction of the next candle.
"""
import sqlite3
import pandas as pd
import numpy as np

def analyze_tick_snaps():
    print("Loading tick data...")
    conn = sqlite3.connect("trading_data.db")
    symbols = pd.read_sql_query("SELECT DISTINCT symbol FROM ticks", conn)['symbol'].tolist()
    
    if not symbols: return
    symbol = symbols[0] # AEDCNY_otc
    print(f"Analyzing {symbol} tick by tick...")
    
    df = pd.read_sql_query(f"SELECT timestamp, price FROM ticks WHERE symbol='{symbol}' AND timestamp > 0 ORDER BY timestamp ASC", conn)
    conn.close()
    
    # We want to group ticks by the minute they belong to
    df['minute_ts'] = (df['timestamp'] // 60) * 60
    
    # Group into minutes
    minutes = df.groupby('minute_ts')
    
    trades = []
    
    for minute, ticks in minutes:
        if len(ticks) < 10: continue
        
        ticks = ticks.sort_values('timestamp')
        
        # Open and Close of THIS minute
        open_p = ticks['price'].iloc[0]
        close_p = ticks['price'].iloc[-1]
        
        # Look at the final 3 seconds
        end_time = ticks['timestamp'].iloc[-1]
        final_ticks = ticks[ticks['timestamp'] >= end_time - 3.0]
        
        if len(final_ticks) < 3: continue
        
        # Calculate tick-to-tick differences in the final 3 seconds
        diffs = final_ticks['price'].diff().dropna()
        
        is_straight_up = (diffs > 0).all() and len(diffs) >= 3
        is_straight_down = (diffs < 0).all() and len(diffs) >= 3
        
        trades.append({
            'minute': minute,
            'close': close_p,
            'straight_up': is_straight_up,
            'straight_down': is_straight_down,
            'diffs_sum': diffs.sum()
        })
        
    res_df = pd.DataFrame(trades)
    res_df = res_df.sort_values('minute').reset_index(drop=True)
    
    # Next minute close vs this minute close
    res_df['next_close'] = res_df['close'].shift(-1)
    res_df['next_dir'] = np.where(res_df['next_close'] > res_df['close'], 1, 0)
    
    # Test Straight-Line Snap (Reversal)
    up_snap = res_df[res_df['straight_up']]
    down_snap = res_df[res_df['straight_down']]
    
    up_wins = len(up_snap) - up_snap['next_dir'].sum() # Bet DOWN
    down_wins = down_snap['next_dir'].sum() # Bet UP
    
    print("\n=== STRAIGHT-LINE SNAP (REVERSAL) ===")
    tot_snap = len(up_snap) + len(down_snap)
    if tot_snap > 0:
        print(f"Total Trades: {tot_snap}")
        print(f"Wins: {up_wins + down_wins}")
        print(f"Win Rate: {(up_wins + down_wins) / tot_snap * 100:.1f}%")
        
    # Test Straight-Line Continuation
    up_wins_c = up_snap['next_dir'].sum() # Bet UP
    down_wins_c = len(down_snap) - down_snap['next_dir'].sum() # Bet DOWN
    
    print("\n=== STRAIGHT-LINE CONTINUATION ===")
    if tot_snap > 0:
        print(f"Total Trades: {tot_snap}")
        print(f"Wins: {up_wins_c + down_wins_c}")
        print(f"Win Rate: {(up_wins_c + down_wins_c) / tot_snap * 100:.1f}%")

if __name__ == "__main__":
    analyze_tick_snaps()
