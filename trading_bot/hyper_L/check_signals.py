"""Quick diagnostic: Check what the current BTC candles look like and
whether any signals would fire RIGHT NOW."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hyperliquid.info import Info
from hyperliquid.utils import constants
from datetime import datetime, timezone
import numpy as np

info = Info(constants.MAINNET_API_URL, skip_ws=True)

# Get current price
mids = info.all_mids()
btc_price = float(mids.get('BTC', 0))
print(f"\n  BTC Price: ${btc_price:,.2f}")

# Get latest 5m candles
now = int(datetime.now(timezone.utc).timestamp() * 1000)
start = now - (30 * 5 * 60 * 1000)  # Last 30 candles
candles = info.candles_snapshot("BTC", "5m", start, now)

print(f"  Got {len(candles)} candles\n")

if not candles:
    print("  No candles!")
    exit()

# Parse
parsed = []
for c in candles:
    parsed.append({
        'time': c.get('t', c.get('T', 0)),
        'open': float(c.get('o', 0)),
        'high': float(c.get('h', 0)),
        'low': float(c.get('l', 0)),
        'close': float(c.get('c', 0)),
        'volume': float(c.get('v', 0)),
    })
parsed.sort(key=lambda x: x['time'])

# Show last 5 candles
print(f"  {'Time':>20} {'Open':>10} {'High':>10} {'Low':>10} {'Close':>10} {'Range':>8} {'Volume':>10}")
print("  " + "-" * 80)
for c in parsed[-5:]:
    dt = datetime.fromtimestamp(c['time']/1000, tz=timezone.utc).strftime('%H:%M:%S')
    rng = c['high'] - c['low']
    print(f"  {dt:>20} ${c['open']:>9,.1f} ${c['high']:>9,.1f} ${c['low']:>9,.1f} ${c['close']:>9,.1f} ${rng:>6,.1f} {c['volume']:>10,.1f}")

# Evaluate latest candle signals
c = parsed[-1]
lookback = 20
if len(parsed) >= lookback + 3:
    body = abs(c['close'] - c['open'])
    if body == 0: body = 0.01
    rng = c['high'] - c['low']
    
    upper_wick = c['high'] - max(c['open'], c['close'])
    lower_wick = min(c['open'], c['close']) - c['low']
    max_wick = max(upper_wick, lower_wick)
    wick_ratio = max_wick / body
    wick_dir = "DOWN" if lower_wick > upper_wick else "UP"
    
    vol_window = [parsed[-(i+1)]['volume'] for i in range(1, min(lookback+1, len(parsed)))]
    avg_vol = np.mean(vol_window) if vol_window else 0.01
    vol_ratio = c['volume'] / avg_vol if avg_vol > 0 else 0
    
    close_window = [parsed[-(i+1)]['close'] for i in range(1, min(lookback+1, len(parsed)))]
    mean_p = np.mean(close_window)
    std_p = np.std(close_window)
    if std_p == 0: std_p = 0.01
    z = (c['close'] - mean_p) / std_p
    
    rsi_period = min(14, len(parsed) - 1)
    gains, losses = [], []
    for j in range(len(parsed)-rsi_period-1, len(parsed)-1):
        d = parsed[j+1]['close'] - parsed[j]['close']
        gains.append(max(d, 0))
        losses.append(abs(min(d, 0)))
    avg_g = np.mean(gains) if gains else 0
    avg_l = np.mean(losses) if losses else 0.01
    if avg_l == 0: avg_l = 0.01
    rsi = 100 - (100 / (1 + avg_g/avg_l))
    
    print(f"\n  ═══════════════════════════════════════")
    print(f"  LATEST CANDLE SIGNAL ANALYSIS")
    print(f"  ═══════════════════════════════════════")
    print(f"  Range:       ${rng:,.1f} {'✅ >= $50' if rng >= 50 else '❌ < $50 (filtered out)'}")
    print(f"  Wick Ratio:  {wick_ratio:.1f} {'✅ >= 2.0' if wick_ratio >= 2.0 else '❌ < 2.0'} (dir: {wick_dir})")
    print(f"  Volume:      {vol_ratio:.1f}x avg {'✅ >= 1.5x' if vol_ratio >= 1.5 else '❌ < 1.5x'}")
    print(f"  Z-Score:     {z:.2f} {'✅ |z| >= 1.5' if abs(z) >= 1.5 else '❌ |z| < 1.5'}")
    print(f"  RSI:         {rsi:.1f} {'✅ extreme' if rsi <= 30 or rsi >= 70 else '❌ neutral (30-70)'}")
    
    confirms = 0
    if wick_ratio >= 2.0: confirms += 1
    if vol_ratio >= 1.5: confirms += 1
    if abs(z) >= 1.5: confirms += 1
    if rsi <= 30 or rsi >= 70: confirms += 1
    
    print(f"\n  CONFIRMATIONS: {confirms}/5")
    if rng < 50:
        print(f"  VERDICT: ❌ FILTERED — Range too small (${rng:.0f} < $50)")
    elif confirms >= 2:
        print(f"  VERDICT: ✅ WOULD TRADE — Signal is live!")
    else:
        print(f"  VERDICT: ⏳ WAITING — Need 2+ confirmations, only have {confirms}")
