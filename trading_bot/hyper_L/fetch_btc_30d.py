"""
Fetch 30 days of BTC 5-minute candles from Hyperliquid.
The API limits 1m candles to ~5000 (3.5 days), so we use 5m 
to get full 30-day coverage for statistically robust analysis.
"""
import os
import sys
import csv
import time
from datetime import datetime, timedelta

# Add parent to path for SDK
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hyperliquid.info import Info
from hyperliquid.utils import constants

COIN = "BTC"
INTERVAL = "5m"
DAYS_BACK = 30
MAX_CANDLES_PER_REQ = 5000
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "btc_5m_30d.csv")

def fetch():
    print("=" * 60)
    print("  HYPERLIQUID 30-DAY BTC DATA VACUUM (5m candles)")
    print("=" * 60)
    
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    end_time = datetime.utcnow()
    start_time = end_time - timedelta(days=DAYS_BACK)
    
    current_start = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)
    
    expected = DAYS_BACK * 24 * 12  # 12 five-min candles per hour
    print(f"\n  Fetching BTC 5m candles from {start_time.date()} to {end_time.date()}")
    print(f"  Expected: ~{expected} candles\n")
    
    all_candles = []
    page = 0
    
    while current_start < end_ms:
        page += 1
        chunk_end = min(current_start + (MAX_CANDLES_PER_REQ * 5 * 60 * 1000), end_ms)
        
        try:
            candles = info.candles_snapshot(COIN, INTERVAL, current_start, chunk_end)
        except Exception as e:
            print(f"  Page {page}: API error: {e}")
            current_start = chunk_end + (5 * 60 * 1000)
            continue
        
        if not candles:
            print(f"  Page {page}: No data for this range. Skipping ahead.")
            current_start = chunk_end + (5 * 60 * 1000)
            continue
        
        all_candles.extend(candles)
        last_ts = candles[-1].get('t', candles[-1].get('T', 0))
        if isinstance(last_ts, (int, float)):
            last_dt = datetime.utcfromtimestamp(last_ts / 1000)
        else:
            last_dt = "?"
        
        print(f"  Page {page}: Got {len(candles)} candles | Last: {last_dt} | Total: {len(all_candles)}")
        
        # Move past the last candle we received
        current_start = int(last_ts) + (5 * 60 * 1000)
        time.sleep(0.3)  # Rate limit courtesy
    
    if not all_candles:
        print("\n  No data retrieved. Exiting.")
        return
    
    # Deduplicate by timestamp
    seen = set()
    unique = []
    for c in all_candles:
        ts = c.get('t', c.get('T', 0))
        if ts not in seen:
            seen.add(ts)
            unique.append(c)
    unique.sort(key=lambda x: x.get('t', x.get('T', 0)))
    
    # Save to CSV
    print(f"\n  Saving {len(unique)} candles to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['datetime', 'open', 'high', 'low', 'close', 'volume'])
        for c in unique:
            ts = c.get('t', c.get('T', 0))
            dt = datetime.utcfromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
            o = c.get('o', c.get('open', 0))
            h = c.get('h', c.get('high', 0))
            l = c.get('l', c.get('low', 0))
            cl = c.get('c', c.get('close', 0))
            v = c.get('v', c.get('volume', 0))
            writer.writerow([dt, o, h, l, cl, v])
    
    first_ts = unique[0].get('t', unique[0].get('T', 0))
    last_ts = unique[-1].get('t', unique[-1].get('T', 0))
    first_close = unique[0].get('c', unique[0].get('close', 0))
    last_close = unique[-1].get('c', unique[-1].get('close', 0))
    
    file_size = os.path.getsize(OUTPUT_FILE) / 1024
    
    print(f"  Done! Saved {len(unique)} candles ({file_size:.1f} KB)")
    print(f"  Range: {datetime.utcfromtimestamp(first_ts/1000)} to {datetime.utcfromtimestamp(last_ts/1000)}")
    print(f"  First Close: ${float(first_close):,.2f}")
    print(f"  Last Close:  ${float(last_close):,.2f}")
    print(f"\n  Ready for God Mode forensics!")

if __name__ == "__main__":
    fetch()
