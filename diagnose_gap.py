import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Sample 5-minute windows every hour from 02:00 to 07:00 UTC
check_windows = [
    ("2026-10-22T02:30:00Z", "2026-10-22T02:40:00Z"),
    ("2026-10-22T03:30:00Z", "2026-10-22T03:40:00Z"),
    ("2026-10-22T04:30:00Z", "2026-10-22T04:40:00Z"),
    ("2026-10-22T05:30:00Z", "2026-10-22T05:40:00Z"),
    ("2026-10-22T06:30:00Z", "2026-10-22T06:40:00Z"),
]

for st, et in check_windows:
    params = {
        'ownerId': OWNER_ID,
        'resource': SERVICE_ID,
        'startTime': st,
        'endTime': et,
        'limit': 100
    }
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            print(f"\nWindow {st[:16]} - {et[11:16]}: {len(logs)} logs")
            for item in reversed(logs):
                msg = item.get("message", "").strip()
                ts = item.get("timestamp", "")[:19]
                if any(k in msg for k in ["SIGNAL", "SKIP", "BLOCK", "DROP", "GATE", "Error", "Traceback", "Exception", "LIVENESS", "Lock"]):
                    print(f"  [{ts}] {msg}")
    except Exception as e:
        print(f"Err {st}: {e}")
    time.sleep(0.3)
