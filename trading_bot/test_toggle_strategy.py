import pandas as pd
import numpy as np

df = pd.read_csv('tick_log.csv')
df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
df['price'] = pd.to_numeric(df['price'], errors='coerce')
df = df.dropna(subset=['timestamp', 'price'])
df = df[df['timestamp'] > 1e9].sort_values('timestamp').reset_index(drop=True)
df['timestamp'] = df['timestamp'].apply(lambda t: t/1000.0 if t > 2e9 else t)

sdf = df[df['symbol'] == 'AEDCNY_otc'].reset_index(drop=True)
prices = sdf['price'].values
timestamps = sdf['timestamp'].values
velocities = np.zeros(len(prices))
velocities[1:] = np.diff(prices)

# Strategy Mode Toggle Simulation
strategy_mode = "reversal" # Initial mode
trades = []
last_trade_time = 0

for i in range(100, len(prices)-60):
    t = timestamps[i]
    price = prices[i]
    vel = velocities[i]
    if abs(vel) < 0.00010: continue
    
    sec = t % 60
    ttb = 60.0 - sec
    
    w100 = velocities[i-99:i+1]
    std_v = np.std(w100)
    if std_v == 0: continue
    
    z_score = (vel - np.mean(w100)) / std_v
    
    p_10_ago = prices[i-10]
    pc10 = abs(price - p_10_ago) / p_10_ago * 10000 if p_10_ago > 0 else 0
    
    v20 = velocities[i-19:i+1]
    flips_20 = sum(1 for j in range(1, len(v20)) if (v20[j] > 0) != (v20[j-1] > 0))
    
    is_core1 = abs(z_score) > 3.5 and flips_20 < 2
    is_core2 = abs(z_score) > 2.5 and ttb > 15.0 and pc10 > 30.0
    
    if not (is_core1 or is_core2): continue
    if t - last_trade_time < 60: continue
    
    last_trade_time = t
    
    # Action based on current mode
    if strategy_mode == "reversal":
        action = "put" if z_score > 0 else "call"
    else: # continuation
        action = "call" if z_score > 0 else "put"
        
    target_ts = (int(t // 60) + 1) * 60 + 1.0
    fut_indices = np.where(timestamps >= target_ts)[0]
    if len(fut_indices) == 0: continue
    expiry_price = prices[fut_indices[0]]
    
    win = (action == "call" and expiry_price > price) or (action == "put" and expiry_price < price)
    
    old_mode = strategy_mode
    if not win:
        # Toggle on loss
        strategy_mode = "continuation" if strategy_mode == "reversal" else "reversal"
        
    trades.append({
        'ts': t, 'price': price, 'z': z_score, 'mode_used': old_mode,
        'action': action, 'win': win, 'next_mode': strategy_mode
    })

tdf = pd.DataFrame(trades)
print(f"Total Trades with Loss-Triggered Strategy Toggle: {len(tdf)}")
print(f"Overall Win Rate: {tdf['win'].mean()*100:.1f}% ({tdf['win'].sum()}/{len(tdf)})")
for idx, r in tdf.iterrows():
    status = "WIN" if r['win'] else "LOSS -> SWITCH"
    print(f"Trade {idx+1:2d} | Mode: {r['mode_used']:<12} | Action: {r['action'].upper():<4} | Result: {status:<15} | Next Mode: {r['next_mode']}")
