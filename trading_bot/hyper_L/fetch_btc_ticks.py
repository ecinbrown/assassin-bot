"""
Hyperliquid BTC Tick Data Fetcher
=================================
Fetches 1-minute candle data for BTC perpetual futures from Hyperliquid's 
public API (no API key needed). Downloads the last 30 days of data.

Each row = 1 minute of price action (Open, High, Low, Close, Volume).
At 1-minute resolution over 30 days, this gives us ~43,200 candles.
"""

import time
import csv
import os
import sys
from datetime import datetime, timedelta

# Add parent dir for shared utilities if needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hyperliquid.info import Info
from hyperliquid.utils import constants

# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════
COIN = "BTC"
INTERVAL = "1m"           # 1-minute candles (highest resolution available)
DAYS_BACK = 30             # Fetch last 30 days for full statistical confidence
MAX_CANDLES_PER_REQ = 5000 # Hyperliquid API limit
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "btc_1m_30d.csv")

def fetch_all_candles():
    """Paginate through the Hyperliquid API to fetch all 1m candles for the past N days."""
    
    print(f"🚀 Initializing Hyperliquid API connection (Mainnet)...")
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    
    end_time_ms = int(time.time() * 1000)
    start_time_ms = end_time_ms - (DAYS_BACK * 24 * 60 * 60 * 1000)
    
    all_candles = []
    current_start = start_time_ms
    page = 1
    
    print(f"📅 Fetching {COIN} {INTERVAL} candles from {datetime.fromtimestamp(start_time_ms/1000).strftime('%Y-%m-%d')} to {datetime.fromtimestamp(end_time_ms/1000).strftime('%Y-%m-%d')}")
    print(f"📊 Expected: ~{DAYS_BACK * 24 * 60} candles\n")
    
    while current_start < end_time_ms:
        try:
            # Each request fetches up to 5000 candles
            chunk_end = min(current_start + (MAX_CANDLES_PER_REQ * 60 * 1000), end_time_ms)
            
            candles = info.candles_snapshot(COIN, INTERVAL, current_start, chunk_end)
            
            if not candles:
                # Try hitting the endpoint directly to see if there's an error
                import requests
                url = constants.MAINNET_API_URL + '/info'
                payload = {'type': 'candleSnapshot', 'req': {'coin': COIN, 'interval': INTERVAL, 'startTime': current_start, 'endTime': chunk_end}}
                r = requests.post(url, json=payload)
                print(f"  Page {page}: No data. Raw API response: {r.text[:200]}")
                # Move forward to avoid infinite loop
                current_start = chunk_end + (60 * 1000)
                continue
                
            all_candles.extend(candles)
            
            # Get the last timestamp and move forward
            last_ts = candles[-1]['t']
            
            print(f"  Page {page}: Got {len(candles)} candles | Last: {datetime.fromtimestamp(last_ts/1000).strftime('%Y-%m-%d %H:%M')} | Total: {len(all_candles)}")
            
            # Move start to after the last candle
            current_start = last_ts + (60 * 1000)  # +1 minute
            page += 1
            
            # Be respectful to the API
            time.sleep(0.5)
            
        except Exception as e:
            print(f"  ❌ Error on page {page}: {e}")
            time.sleep(2)
            continue
    
    return all_candles

def save_to_csv(candles):
    """Save candles to CSV for forensics analysis."""
    
    print(f"\n💾 Saving {len(candles)} candles to {OUTPUT_FILE}...")
    
    with open(OUTPUT_FILE, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'datetime', 'open', 'high', 'low', 'close', 'volume', 'num_trades'])
        
        for c in candles:
            ts = c.get('t', c.get('T', 0))
            dt_str = datetime.fromtimestamp(ts / 1000).strftime('%Y-%m-%d %H:%M:%S')
            
            writer.writerow([
                ts,
                dt_str,
                c.get('o', 0),
                c.get('h', 0),
                c.get('l', 0),
                c.get('c', 0),
                c.get('v', 0),
                c.get('n', 0)
            ])
    
    # Summary stats
    file_size = os.path.getsize(OUTPUT_FILE)
    print(f"✅ Done! Saved {len(candles)} candles ({file_size / 1024:.1f} KB)")
    
    if candles:
        first_dt = datetime.fromtimestamp(candles[0]['t'] / 1000).strftime('%Y-%m-%d %H:%M')
        last_dt = datetime.fromtimestamp(candles[-1]['t'] / 1000).strftime('%Y-%m-%d %H:%M')
        print(f"📅 Range: {first_dt} → {last_dt}")
        print(f"📊 First Close: ${float(candles[0].get('c', 0)):,.2f}")
        print(f"📊 Last Close:  ${float(candles[-1].get('c', 0)):,.2f}")

if __name__ == "__main__":
    print("=" * 60)
    print("  HYPERLIQUID BTC DATA VACUUM")
    print("  No API Key Required | Public Endpoint")
    print("=" * 60)
    print()
    
    candles = fetch_all_candles()
    
    if candles:
        save_to_csv(candles)
        print(f"\n🔬 Ready for forensics! Run: python hyper_L/snapback_forensics.py")
    else:
        print("❌ No data fetched. Check your internet connection.")
