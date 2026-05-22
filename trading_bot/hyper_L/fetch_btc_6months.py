"""
Fetch 6 months of BTC 1-hour candles from Binance public API.
No API key required. BTC price action is identical across all 
exchanges due to arbitrage, so this data is valid for Hyperliquid backtesting.
"""
import os, csv, time
from datetime import datetime, timedelta, timezone
import urllib.request
import json

OUTPUT = os.path.join(os.path.dirname(__file__), "btc_1h_6months.csv")
SYMBOL = "BTCUSDT"
INTERVAL = "1h"
MONTHS = 6
LIMIT = 1000  # Binance max per request

def fetch_binance_klines(symbol, interval, start_ms, end_ms, limit=1000):
    """Fetch klines from Binance public API."""
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={symbol}&interval={interval}"
        f"&startTime={start_ms}&endTime={end_ms}&limit={limit}"
    )
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read().decode())

def main():
    print("=" * 60)
    print("  6-MONTH BTC DATA VACUUM (Binance 1h candles)")
    print("=" * 60)
    
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=MONTHS * 30)
    
    cur_ms = int(start.timestamp() * 1000)
    end_ms = int(now.timestamp() * 1000)
    
    expected = MONTHS * 30 * 24
    print(f"\n  Fetching {SYMBOL} 1h candles: {start.date()} to {now.date()}")
    print(f"  Expected: ~{expected} candles\n")
    
    all_candles = []
    page = 0
    
    while cur_ms < end_ms:
        page += 1
        try:
            klines = fetch_binance_klines(SYMBOL, INTERVAL, cur_ms, end_ms, LIMIT)
        except Exception as e:
            print(f"  Page {page}: Error: {e}. Retrying in 5s...")
            time.sleep(5)
            continue
        
        if not klines:
            break
        
        for k in klines:
            all_candles.append({
                'time_ms': k[0],
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4]),
                'volume': float(k[5]),
            })
        
        last_dt = datetime.fromtimestamp(klines[-1][0] / 1000, tz=timezone.utc)
        print(f"  Page {page}: Got {len(klines)} | Last: {last_dt} | Total: {len(all_candles)}")
        
        cur_ms = klines[-1][0] + (60 * 60 * 1000)  # Next hour
        time.sleep(0.2)  # Rate limit
    
    # Deduplicate
    seen = set()
    unique = []
    for c in all_candles:
        if c['time_ms'] not in seen:
            seen.add(c['time_ms'])
            unique.append(c)
    unique.sort(key=lambda x: x['time_ms'])
    
    # Save CSV
    with open(OUTPUT, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['datetime', 'open', 'high', 'low', 'close', 'volume'])
        for c in unique:
            dt = datetime.fromtimestamp(c['time_ms'] / 1000, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
            w.writerow([dt, c['open'], c['high'], c['low'], c['close'], c['volume']])
    
    days = (unique[-1]['time_ms'] - unique[0]['time_ms']) / (1000 * 60 * 60 * 24)
    size_kb = os.path.getsize(OUTPUT) / 1024
    
    print(f"\n  Saved {len(unique)} candles ({size_kb:.1f} KB)")
    print(f"  Days covered: {days:.0f}")
    print(f"  First: ${unique[0]['close']:,.0f} ({datetime.fromtimestamp(unique[0]['time_ms']/1000, tz=timezone.utc).date()})")
    print(f"  Last:  ${unique[-1]['close']:,.0f} ({datetime.fromtimestamp(unique[-1]['time_ms']/1000, tz=timezone.utc).date()})")

if __name__ == "__main__":
    main()
