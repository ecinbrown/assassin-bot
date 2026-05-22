"""
Fetch maximum historical BTC data from Hyperliquid using 15m candles.
15m resolution × 5000 candles = ~52 days of coverage.
This gives us the statistical depth to absolutely verify The Assassin.
"""
import os, sys, csv, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from hyperliquid.info import Info
from hyperliquid.utils import constants

COIN = "BTC"
INTERVAL = "15m"
DAYS_BACK = 60
MAX_CANDLES = 5000
OUTPUT = os.path.join(os.path.dirname(__file__), "btc_15m_60d.csv")

def fetch():
    print("=" * 60)
    print("  HYPERLIQUID 60-DAY BTC DATA VACUUM (15m candles)")
    print("=" * 60)
    
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=DAYS_BACK)
    
    cur = int(start.timestamp() * 1000)
    end = int(now.timestamp() * 1000)
    
    expected = DAYS_BACK * 24 * 4
    print(f"\n  Fetching BTC 15m candles: {start.date()} to {now.date()}")
    print(f"  Expected: ~{expected} candles\n")
    
    all_c = []
    page = 0
    
    while cur < end:
        page += 1
        chunk = min(cur + (MAX_CANDLES * 15 * 60 * 1000), end)
        
        try:
            candles = info.candles_snapshot(COIN, INTERVAL, cur, chunk)
        except Exception as e:
            print(f"  Page {page}: Error: {e}")
            cur = chunk + (15 * 60 * 1000)
            continue
        
        if not candles:
            cur = chunk + (15 * 60 * 1000)
            continue
        
        all_c.extend(candles)
        last_ts = candles[-1].get('t', candles[-1].get('T', 0))
        last_dt = datetime.fromtimestamp(last_ts / 1000, tz=timezone.utc)
        print(f"  Page {page}: Got {len(candles)} | Last: {last_dt} | Total: {len(all_c)}")
        
        cur = int(last_ts) + (15 * 60 * 1000)
        time.sleep(0.3)
    
    if not all_c:
        print("  No data. Exiting.")
        return
    
    # Deduplicate
    seen = set()
    unique = []
    for c in all_c:
        ts = c.get('t', c.get('T', 0))
        if ts not in seen:
            seen.add(ts)
            unique.append(c)
    unique.sort(key=lambda x: x.get('t', x.get('T', 0)))
    
    with open(OUTPUT, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['datetime', 'open', 'high', 'low', 'close', 'volume'])
        for c in unique:
            ts = c.get('t', c.get('T', 0))
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            w.writerow([dt, c.get('o', 0), c.get('h', 0), c.get('l', 0), c.get('c', 0), c.get('v', 0)])
    
    first_ts = unique[0].get('t', unique[0].get('T', 0))
    last_ts = unique[-1].get('t', unique[-1].get('T', 0))
    days_covered = (last_ts - first_ts) / (1000 * 60 * 60 * 24)
    
    print(f"\n  Saved {len(unique)} candles ({os.path.getsize(OUTPUT)/1024:.1f} KB)")
    print(f"  Range: {datetime.fromtimestamp(first_ts/1000, tz=timezone.utc).date()} to {datetime.fromtimestamp(last_ts/1000, tz=timezone.utc).date()}")
    print(f"  Days covered: {days_covered:.1f}")
    print(f"  First: ${float(unique[0].get('c', 0)):,.0f} | Last: ${float(unique[-1].get('c', 0)):,.0f}")

if __name__ == "__main__":
    fetch()
