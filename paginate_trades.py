import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

cursor = None
trades = []
pages = 0

print("Paginating backwards through Render logs...", flush=True)

while pages < 25:
    pages += 1
    params = {
        'ownerId': OWNER_ID,
        'resource': SERVICE_ID,
        'direction': 'backward',
        'limit': 100
    }
    if cursor:
        params['cursor'] = cursor

    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                break
            
            for item in logs:
                msg = item.get("message", "").strip()
                ts = item.get("timestamp", "")[:19]
                if any(k in msg for k in ["[BG-SETTLER]", "TRADE OPENED", "Scorecard", "LIVENESS ALERT"]):
                    trades.append((ts, msg))
            
            # The next cursor is the id of the oldest log in this batch (last element)
            cursor = logs[-1].get("id")
            oldest_ts = logs[-1].get("timestamp", "")[:19]
            if oldest_ts < "2026-10-22T01:40:00":
                break
    except Exception as e:
        print(f"Error on page {pages}: {e}", flush=True)
        break
    time.sleep(0.3)

print(f"\nFinished scanning {pages} pages. Oldest timestamp reached: {oldest_ts}")
print(f"--- FOUND {len(trades)} TRADE/SETTLER EVENTS ---")
# Deduplicate and sort forward
unique_trades = list(dict.fromkeys(trades))
for ts, msg in sorted(unique_trades, key=lambda x: x[0]):
    print(f"[{ts}] {msg}")
