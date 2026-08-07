import pandas as pd
import numpy as np
import math
import secrets

class CSPRNGStrategy:
    """
    CSPRNG Cryptographic Feed Analyzer & Strategy Generator
    Analyzes synthetic OTC tick feeds for non-random cryptographic / PRNG patterns.
    """
    def __init__(self, entropy_threshold: float = 0.75):
        self.entropy_threshold = entropy_threshold
        self.sys_random = secrets.SystemRandom()

    def calc_binary_entropy(self, velocities: list) -> float:
        up = sum(1 for v in velocities if v > 0)
        down = sum(1 for v in velocities if v < 0)
        total = up + down
        if total < 10:
            return 1.0
        p_up = up / total
        p_down = down / total
        if p_up == 0 or p_down == 0:
            return 0.0
        return float(- (p_up * math.log2(p_up) + p_down * math.log2(p_down)))

    def analyze_signal(self, velocities: list, price_history: list):
        """
        Analyzes PRNG entropy + direction bias.
        Returns: ('call' / 'put' / None, trigger_description)
        """
        if len(velocities) < 20:
            return None, ""
            
        recent_20 = velocities[-20:]
        entropy = self.calc_binary_entropy(recent_20)
        
        # If entropy is low (< 0.75), the PRNG is currently generating a non-random trend run
        if entropy < self.entropy_threshold:
            net_move = sum(recent_20)
            if net_move > 0:
                # PRNG upward expansion run detected
                return 'call', f"CSPRNG PRNG-RUN CALL (Entropy={entropy:.3f}, Net={net_move:.5f})"
            elif net_move < 0:
                # PRNG downward expansion run detected
                return 'put', f"CSPRNG PRNG-RUN PUT (Entropy={entropy:.3f}, Net={net_move:.5f})"
                
        return None, ""

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

csprng_strat = CSPRNGStrategy(entropy_threshold=0.70)
trades = []
last_trade_time = 0

for i in range(50, len(prices)-60):
    t = timestamps[i]
    price = prices[i]
    vel = velocities[i]
    if abs(vel) < 0.00010: continue
    
    if t - last_trade_time < 60: continue
    
    action, desc = csprng_strat.analyze_signal(velocities[:i+1], prices[:i+1])
    if not action: continue
    
    last_trade_time = t
    
    target_ts = (int(t // 60) + 1) * 60 + 1.0
    fut_indices = np.where(timestamps >= target_ts)[0]
    if len(fut_indices) == 0: continue
    expiry_price = prices[fut_indices[0]]
    
    win = (action == "call" and expiry_price > price) or (action == "put" and expiry_price < price)
    
    trades.append({
        'ts': t, 'price': price, 'action': action, 'desc': desc, 'win': win
    })

tdf = pd.DataFrame(trades)
print(f"\n==========================================")
print(f"CSPRNG STRATEGY OVERALL RESULTS:")
print(f"Total Signals: {len(tdf)}")
if len(tdf) > 0:
    print(f"Win Rate: {tdf['win'].mean()*100:.2f}% ({tdf['win'].sum()}/{len(tdf)})")
print(f"==========================================")
