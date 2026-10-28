import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# We want everything since the deploy on Oct 18 ~10:00 UTC
start_time = "2026-10-18T10:00:00Z"
events = []
seen = set()

for page in range(150):
    params = {
        "ownerId": OWNER_ID,
        "resource": SERVICE_ID,
        "direction": "forward",
        "limit": "100",
        "startTime": start_time
    }
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json"
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                break
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                if any(k in msg for k in ["[BG-SETTLER]", "TAKE_IT", "Trade Executed", "Starting Bankroll", "Active Strategy Mode", "Reset to Base", "CRITICAL", "ERROR"]):
                    events.append((ts, msg))
            nx = data.get("nextStartTime")
            if not nx or nx == start_time or not data.get("hasMore", True):
                break
            start_time = nx
            time.sleep(0.15)
    except Exception as e:
        print(f"Err: {e}")
        break

print(f"Total events found since deploy: {len(events)}")
with open("deploy_trade_log.txt", "w", encoding="utf-8") as f:
    for ts, msg in events:
        f.write(f"[{ts}] {msg}\n")
        if any(k in msg for k in ["[BG-SETTLER]", "Starting Bankroll", "TAKE_IT"]):
            print(f"[{ts}] {msg}")
