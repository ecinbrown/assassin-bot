import urllib.request, urllib.parse, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&startTime=2026-10-12T16:55:00Z&endTime=2026-10-12T17:05:00Z&limit=100"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())
logs = data.get("logs", [])
print(f"Found {len(logs)} logs between 16:55 and 17:05 UTC:")
for item in reversed(logs):
    msg = item.get("message", "").strip()
    ts = item.get("timestamp", "")
    if any(k in msg for k in ["XRP", "SIGNAL", "Trade", "EVAL", "SKIP", "DROP"]):
        print(f"[{ts}] {msg}")
