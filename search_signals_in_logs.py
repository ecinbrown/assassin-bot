import urllib.request, urllib.parse, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

end_time = None
all_logs = []
for page in range(30):
    params = {
        "ownerId": OWNER_ID,
        "resource": SERVICE_ID,
        "direction": "backward",
        "limit": "100"
    }
    if end_time:
        params["endTime"] = end_time
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        resp = urllib.request.urlopen(req)
        data = json.loads(resp.read().decode())
        logs = data.get("logs", [])
        if not logs: break
        all_logs.extend(logs)
        end_time = data.get("nextEndTime")
        if not end_time: break
    except Exception as e:
        print("Err:", e)
        break

print(f"Total logs fetched: {len(all_logs)}")
# Search for startup messages, signal checks, or trade events
events = []
for item in reversed(all_logs):
    msg = item.get("message", "")
    ts = item.get("timestamp", "")
    if any(k in msg for k in [
        "Armed with", "HybridSignalEngine", "STRATEGY MODE", "Signal", 
        "EXTREME_REVERSAL", "TAKE_IT", "Trade Executed", "DROP", "SKIP", 
        "Evaluating", "Active Strategy", "Startup", "Preload", "Traceback", "ERROR", "CRITICAL"
    ]):
        events.append((ts, msg.strip()))

print(f"\nFound {len(events)} relevant events:")
for ts, msg in events[-40:]:
    print(f"[{ts}] {msg}")
