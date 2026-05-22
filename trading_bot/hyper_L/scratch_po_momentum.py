"""
POCKETOPTION 90% EDGE FINDER (MOMENTUM)
========================================
We have ~255k ticks. We will group them into 1-minute candles.
We need to predict the direction of the NEXT 1-minute candle (Binary Options expiration).
We will test extreme momentum leading into the candle close.
"""
import sqlite3
import pandas as pd
import numpy as np

def analyze_pocket_edge():
    print("Loading tick data...")
    conn = sqlite3.connect("trading_data.db")
    
    # Check what symbols we have
    symbols = pd.read_sql_query("SELECT DISTINCT symbol FROM ticks", conn)['symbol'].tolist()
    print("Symbols found:", symbols)
    
    if not symbols:
        print("No symbols found.")
        return
        
    symbol = symbols[0] # Just use the first one, likely a major pair or OTC
    print(f"Analyzing {symbol}...")
    
    # Load all ticks for this symbol, filter out 0.0 timestamp
    df = pd.read_sql_query(f"SELECT timestamp, price FROM ticks WHERE symbol='{symbol}' AND timestamp > 0 ORDER BY timestamp ASC", conn)
    conn.close()
    
    if len(df) == 0:
        print("No valid tick data.")
        return
        
    # Convert timestamp to datetime
    df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
    df.set_index('datetime', inplace=True)
    
    print(f"Total ticks: {len(df)}")
    
    # Resample to 1-minute candles
    candles_1m = df['price'].resample('1Min').ohlc()
    candles_1m = candles_1m.dropna()
    
    print(f"Constructed {len(candles_1m)} 1-minute candles.")
    
    # Calculate some momentum metrics
    # 1. Body size
    candles_1m['body'] = candles_1m['close'] - candles_1m['open']
    candles_1m['body_abs'] = candles_1m['body'].abs()
    
    # 2. Wick sizes
    candles_1m['upper_wick'] = candles_1m['high'] - candles_1m[['open', 'close']].max(axis=1)
    candles_1m['lower_wick'] = candles_1m[['open', 'close']].min(axis=1) - candles_1m['low']
    
    # 3. Previous candle momentum
    candles_1m['prev_body'] = candles_1m['body'].shift(1)
    candles_1m['prev_body_abs'] = candles_1m['body_abs'].shift(1)
    
    # 4. Next candle target (Binary Options: did it close higher or lower?)
    # 1 = UP, 0 = DOWN
    candles_1m['next_dir'] = np.where(candles_1m['close'].shift(-1) > candles_1m['close'], 1, 0)
    
    # Let's try to find a 90% edge.
    # What if we look for an extremely large, full-bodied candle with no wick in the direction of the trend?
    # This indicates terminal momentum (exhaustion) OR massive continuation.
    
    # Filter: massive body
    body_mean = candles_1m['body_abs'].mean()
    body_std = candles_1m['body_abs'].std()
    
    results = []
    
    # Test 1: Continuation on massive momentum
    for mult in [2.0, 3.0, 4.0]:
        threshold = body_mean + (mult * body_std)
        # Big green candle, no upper wick -> bet UP on next
        big_green = (candles_1m['body'] > threshold) & (candles_1m['upper_wick'] < body_mean * 0.1)
        # Big red candle, no lower wick -> bet DOWN on next
        big_red = (candles_1m['body'] < -threshold) & (candles_1m['lower_wick'] < body_mean * 0.1)
        
        green_trades = candles_1m[big_green]
        red_trades = candles_1m[big_red]
        
        green_wins = green_trades['next_dir'].sum()
        red_wins = len(red_trades) - red_trades['next_dir'].sum()
        
        tot_trades = len(green_trades) + len(red_trades)
        if tot_trades > 0:
            wr = (green_wins + red_wins) / tot_trades * 100
            results.append((f"Continuation (Mult {mult})", tot_trades, wr))
            
    # Test 2: Reversal on massive momentum (Exhaustion / Snapback)
    for mult in [2.0, 3.0, 4.0]:
        threshold = body_mean + (mult * body_std)
        # Big green candle -> bet DOWN on next
        big_green = (candles_1m['body'] > threshold)
        # Big red candle -> bet UP on next
        big_red = (candles_1m['body'] < -threshold)
        
        green_trades = candles_1m[big_green]
        red_trades = candles_1m[big_red]
        
        # Bet DOWN so win if next_dir == 0
        green_wins = len(green_trades) - green_trades['next_dir'].sum()
        # Bet UP so win if next_dir == 1
        red_wins = red_trades['next_dir'].sum()
        
        tot_trades = len(green_trades) + len(red_trades)
        if tot_trades > 0:
            wr = (green_wins + red_wins) / tot_trades * 100
            results.append((f"Reversal (Mult {mult})", tot_trades, wr))

    # Test 3: Multiple consecutive candles (Momentum build-up)
    for count in [3, 4, 5]:
        # Count consecutive greens
        c = candles_1m['body'] > 0
        cons_green = c.groupby((~c).cumsum()).cumcount() >= count
        # Count consecutive reds
        c2 = candles_1m['body'] < 0
        cons_red = c2.groupby((~c2).cumsum()).cumcount() >= count
        
        # Bet Continuation
        green_trades = candles_1m[cons_green]
        red_trades = candles_1m[cons_red]
        
        green_wins_cont = green_trades['next_dir'].sum()
        red_wins_cont = len(red_trades) - red_trades['next_dir'].sum()
        tot = len(green_trades) + len(red_trades)
        if tot > 0:
            results.append((f"{count} Cons Continuation", tot, (green_wins_cont + red_wins_cont) / tot * 100))
            
        # Bet Reversal
        green_wins_rev = len(green_trades) - green_trades['next_dir'].sum()
        red_wins_rev = red_trades['next_dir'].sum()
        if tot > 0:
            results.append((f"{count} Cons Reversal", tot, (green_wins_rev + red_wins_rev) / tot * 100))

    print("\nRESULTS:")
    print(f"{'Strategy':<30} | {'Trades':<6} | {'WinRate%':<8}")
    print("-" * 50)
    for r in sorted(results, key=lambda x: x[2], reverse=True):
        print(f"{r[0]:<30} | {r[1]:<6} | {r[2]:.1f}%")

if __name__ == "__main__":
    analyze_pocket_edge()
