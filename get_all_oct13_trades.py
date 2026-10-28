import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

end_time = None
events = []

for page in range(60):
    params = {"ownerId": OWNER_ID, "resource": SERVICE_ID, "direction": "backward", "limit": "100"}
    if end_time:
        params["endTime"] = end_time
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=8)
        data = json.loads(resp.read().decode())
        logs = data.get("logs", [])
        if not logs: break
        for item in logs:
            msg = item.get("message", "").strip()
            ts = item.get("timestamp", "")
            if any(k in msg for k in ["[BG-SETTLER]", "Trade Executed", "DAILY SUMMARY", "Active Trades", "Execution Failed"]):
                events.append((ts, msg))
        nx = data.get("nextEndTime")
        if not nx or nx == end_time: break
        end_time = nx
        # Stop if we went past yesterday 19:00 UTC
        if logs[-1].get("timestamp", "") < "2026-10-12T19:00:00Z":
            break
    except Exception as e:
        print(f"Error page {page}: {e}")
        break

print(f"Total matching trade/summary events: {len(events)}")
for ts, msg in sorted(events, key=lambda x: x[0]):
    print(f"[{ts}] {msg}")
