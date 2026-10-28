import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

windows = [
    ("2026-10-22T01:35:00Z", "2026-10-22T03:00:00Z"),
    ("2026-10-22T03:00:00Z", "2026-10-22T05:00:00Z"),
    ("2026-10-22T05:00:00Z", "2026-10-22T07:05:00Z"),
]

all_trades = []
for start_t, end_t in windows:
    params = {
        'ownerId': OWNER_ID,
        'resource': SERVICE_ID,
        'startTime': start_t,
        'endTime': end_t,
        'limit': 500
    }
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            for item in reversed(logs):
                msg = item.get("message", "").strip()
                ts = item.get("timestamp", "")[:19]
                if any(k in msg for k in ["[BG-SETTLER]", "Scorecard:", "TRADE OPENED"]):
                    if "Candle Closed" not in msg:
                        all_trades.append((ts, msg))
    except Exception as e:
        print(f"Error in window {start_t}: {e}")
    time.sleep(0.5)

print(f"--- TOTAL TRADE EVENTS FOUND: {len(all_trades)} ---")
for ts, msg in all_trades:
    print(f"[{ts}] {msg}")
