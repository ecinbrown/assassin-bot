import pandas as pd
import numpy as np
import math
import secrets

class CSPRNGEngine:
    def __init__(self):
        self.sys_random = secrets.SystemRandom()

    def calc_binary_entropy(self, velocities: list) -> float:
        """Calculates binary Shannon entropy H(p) over tick directions (+1 vs -1)."""
        up = sum(1 for v in velocities if v > 0)
        down = sum(1 for v in velocities if v < 0)
        total = up + down
        if total < 10:
            return 1.0
        p_up = up / total
        p_down = down / total
        if p_up == 0 or p_down == 0:
            return 0.0
        entropy = - (p_up * math.log2(p_up) + p_down * math.log2(p_down))
        return float(entropy)

    def monte_carlo_verify(self, velocities: list, proposed_action: str, n_simulations: int = 300, horizon_ticks: int = 30) -> float:
        if len(velocities) < 15:
            return 0.50
        vel_sample = [v for v in velocities if v != 0]
        if not vel_sample:
            return 0.50
        wins = 0
        for _ in range(n_simulations):
            cumulative_delta = 0.0
            for _ in range(horizon_ticks):
                rand_vel = self.sys_random.choice(vel_sample)
                cumulative_delta += rand_vel
            if proposed_action == "call" and cumulative_delta > 0:
                wins += 1
            elif proposed_action == "put" and cumulative_delta < 0:
                wins += 1
        return wins / float(n_simulations)

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

csprng = CSPRNGEngine()
strategy_mode = "reversal"
trades = []
last_trade_time = 0

entropy_blocked = 0
mc_blocked = 0

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
    
    # CSPRNG Binary Entropy Filter: Allow trades only when entropy < 0.96 (non-noisy market)
    entropy = csprng.calc_binary_entropy(velocities[i-30:i+1])
    if entropy > 0.96:
        entropy_blocked += 1
        continue
        
    # Action selection
    if strategy_mode == "reversal":
        action = "put" if z_score > 0 else "call"
    else:
        action = "call" if z_score > 0 else "put"
        
    last_trade_time = t
    
    target_ts = (int(t // 60) + 1) * 60 + 1.0
    fut_indices = np.where(timestamps >= target_ts)[0]
    if len(fut_indices) == 0: continue
    expiry_price = prices[fut_indices[0]]
    
    win = (action == "call" and expiry_price > price) or (action == "put" and expiry_price < price)
    
    old_mode = strategy_mode
    if not win:
        strategy_mode = "continuation" if strategy_mode == "reversal" else "reversal"
        
    trades.append({
        'ts': t, 'price': price, 'z': z_score, 'entropy': entropy,
        'mode_used': old_mode, 'action': action, 'win': win, 'next_mode': strategy_mode
    })

tdf = pd.DataFrame(trades)
print(f"=== Calibrated CSPRNG Strategy Simulation Results ===")
print(f"Entropy Blocked Signals: {entropy_blocked}")
print(f"Final Executed Trades: {len(tdf)}")
if len(tdf) > 0:
    print(f"CSPRNG Filtered Win Rate: {tdf['win'].mean()*100:.1f}% ({tdf['win'].sum()}/{len(tdf)})")
    for idx, r in tdf.iterrows():
        status = "WIN" if r['win'] else "LOSS -> SWITCH"
        print(f"Trade {idx+1:2d} | Mode: {r['mode_used']:<12} | Act: {r['action'].upper():<4} | Entropy: {r['entropy']:.3f} | Result: {status:<15}")
