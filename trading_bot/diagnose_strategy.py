import pandas as pd
import numpy as np
import time, datetime

df = pd.read_csv('tick_log.csv')
print(f"Total tick rows: {len(df)}")
# Drop header or non-numeric rows and timestamp == 0
df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
df['price'] = pd.to_numeric(df['price'], errors='coerce')
df = df.dropna(subset=['timestamp', 'price'])
df = df[df['timestamp'] > 1e9].sort_values('timestamp').reset_index(drop=True)

# convert ms to s if needed
df['timestamp'] = df['timestamp'].apply(lambda t: t/1000.0 if t > 2e9 else t)
df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')

print(f"Time range: {df['datetime'].min()} to {df['datetime'].max()}")

# Simulate LogicEngine Strategy (Reversal on Spike) vs Continuation on Spike
# LogicEngine parameters:
# Window 100
# CORE 1: abs(z) > 3.5 and flips_20 < 2 -> REVERSAL (potential_action = put if z>0 else call)
# CORE 2: abs(z) > 2.5 and ttb > 15.0 and pc10 > 30.0 -> REVERSAL

symbols = df['symbol'].unique()

for sym in symbols:
    sdf = df[df['symbol'] == sym].reset_index(drop=True)
    if len(sdf) < 200: continue
    
    print(f"\n--- Symbol: {sym} (Total ticks: {len(sdf)}) ---")
    
    prices = sdf['price'].values
    timestamps = sdf['timestamp'].values
    dtimes = sdf['datetime'].values
    
    velocities = np.zeros(len(prices))
    velocities[1:] = np.diff(prices)
    
    reversal_trades = []
    continuation_trades = []
    
    last_trade_time = 0
    
    for i in range(100, len(prices)-60):
        t = timestamps[i]
        price = prices[i]
        dt = dtimes[i]
        
        vel = velocities[i]
        if abs(vel) < 0.00010: continue
        
        sec = t % 60
        ttb = 60.0 - sec
        
        w100 = velocities[i-99:i+1]
        std_v = np.std(w100)
        if std_v == 0: continue
        
        z_score = (vel - np.mean(w100)) / std_v
        
        # pc10
        p_10_ago = prices[i-10]
        pc10 = abs(price - p_10_ago) / p_10_ago * 10000 if p_10_ago > 0 else 0
        
        # flips_20
        v20 = velocities[i-19:i+1]
        flips_20 = sum(1 for j in range(1, len(v20)) if (v20[j] > 0) != (v20[j-1] > 0))
        
        is_core1 = abs(z_score) > 3.5 and flips_20 < 2
        is_core2 = abs(z_score) > 2.5 and ttb > 15.0 and pc10 > 30.0
        
        if not (is_core1 or is_core2):
            continue
            
        if t - last_trade_time < 60:
            continue
            
        last_trade_time = t
        
        # Signal direction
        reversal_act = "put" if z_score > 0 else "call"
        continuation_act = "call" if z_score > 0 else "put"
        
        # Outcome at minute expiry: (next candle rollover ts)
        target_ts = (int(t // 60) + 1) * 60 + 1.0
        
        # find price at target_ts
        fut_indices = np.where(timestamps >= target_ts)[0]
        if len(fut_indices) == 0: continue
        expiry_price = prices[fut_indices[0]]
        
        rev_win = (reversal_act == "call" and expiry_price > price) or (reversal_act == "put" and expiry_price < price)
        cont_win = (continuation_act == "call" and expiry_price > price) or (continuation_act == "put" and expiry_price < price)
        
        rule_type = "CORE1" if is_core1 else "CORE2"
        date_str = str(pd.Timestamp(dt).date())
        hour_str = pd.Timestamp(dt).hour
        
        reversal_trades.append({'dt': dt, 'date': date_str, 'hour': hour_str, 'rule': rule_type, 'z': z_score, 'won': rev_win})
        continuation_trades.append({'dt': dt, 'date': date_str, 'hour': hour_str, 'rule': rule_type, 'z': z_score, 'won': cont_win})

    tdf_rev = pd.DataFrame(reversal_trades)
    tdf_cont = pd.DataFrame(continuation_trades)
    
    if len(tdf_rev) == 0:
        print("No signals generated.")
        continue
        
    print(f"Total Signals: {len(tdf_rev)}")
    print(f"OVERALL Reversal Win Rate: {tdf_rev['won'].mean()*100:.1f}% ({tdf_rev['won'].sum()}/{len(tdf_rev)})")
    print(f"OVERALL Continuation Win Rate: {tdf_cont['won'].mean()*100:.1f}% ({tdf_cont['won'].sum()}/{len(tdf_cont)})")
    
    print("\n--- Breakdown by Date (Reversal Strategy) ---")
    for d, g in tdf_rev.groupby('date'):
        wr = g['won'].mean() * 100
        print(f"  Date {d}: Trades={len(g)}, WinRate={wr:.1f}% ({g['won'].sum()}/{len(g)})")
        
    print("\n--- Breakdown by Date (Continuation Strategy) ---")
    for d, g in tdf_cont.groupby('date'):
        wr = g['won'].mean() * 100
        print(f"  Date {d}: Trades={len(g)}, WinRate={wr:.1f}% ({g['won'].sum()}/{len(g)})")
