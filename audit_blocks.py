import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

end_time = None
signals = 0
blocked_concurrency = 0
blocked_cooldown = 0
trades_executed = 0
settlements = 0

for page in range(30):
    params = {"ownerId": OWNER_ID, "resource": SERVICE_ID, "direction": "backward", "limit": "100",
              "startTime": "2026-10-19T07:04:00Z"}
    if end_time:
        params["endTime"] = end_time
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs: break
            for item in logs:
                msg = item.get("message", "").strip()
                if "TAKE_IT" in msg: signals += 1
                if "[CONCURRENCY]" in msg: blocked_concurrency += 1
                if "COOLDOWN" in msg: blocked_cooldown += 1
                if "Trade Executed" in msg: trades_executed += 1
                if "[BG-SETTLER]" in msg: settlements += 1
            nx = data.get("nextEndTime")
            if not nx or nx == end_time: break
            end_time = nx
            time.sleep(0.15)
    except Exception as e:
        print(f"Err: {e}")
        break

print(f"=== Since deploy (07:04 UTC) ===")
print(f"Signals generated (TAKE_IT): {signals}")
print(f"Blocked by CONCURRENCY (max 1 trade): {blocked_concurrency}")
print(f"Blocked by COOLDOWN: {blocked_cooldown}")
print(f"Trades executed: {trades_executed}")
print(f"Settlements: {settlements}")
