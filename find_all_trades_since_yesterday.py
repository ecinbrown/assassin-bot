import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Step through 2-hour windows from yesterday 19:00 UTC to today 13:00 UTC
windows = [
    ("2026-10-12T19:00:00Z", "2026-10-12T22:00:00Z"),
    ("2026-10-12T22:00:00Z", "2026-10-13T01:00:00Z"),
    ("2026-10-13T01:00:00Z", "2026-10-13T04:00:00Z"),
    ("2026-10-13T04:00:00Z", "2026-10-13T07:00:00Z"),
    ("2026-10-13T07:00:00Z", "2026-10-13T10:00:00Z"),
    ("2026-10-13T10:00:00Z", "2026-10-13T13:00:00Z"),
]

all_signals_and_trades = []

for start_t, end_t in windows:
    print(f"Scanning window {start_t} to {end_t}...")
    url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&startTime={start_t}&endTime={end_t}&limit=100"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode())
        logs = data.get("logs", [])
        for item in logs:
            msg = item.get("message", "").strip()
            ts = item.get("timestamp", "")
            if any(k in msg for k in [
                "SIGNAL", "Trade", "SETTLER", "WIN", "LOSS", "TAKE_IT", 
                "inactive", "Executing", "Executed", "Skipping", "GATE", "DROP", "CRITICAL"
            ]):
                if "Candle Closed" not in msg:
                    all_signals_and_trades.append((ts, msg))
    except Exception as e:
        print(f"Error in window {start_t}: {e}")
    time.sleep(0.5)

print(f"\nTotal events found: {len(all_signals_and_trades)}")
for ts, msg in sorted(all_signals_and_trades, key=lambda x: x[0]):
    print(f"[{ts}] {msg}")
