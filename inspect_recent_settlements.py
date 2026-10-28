import urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Search logs specifically for BG-SETTLER or Trade Executed
url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&limit=100&direction=backward"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())
print(f"Fetched {len(data.get('logs', []))} logs.")
for item in reversed(data.get('logs', [])):
    msg = item.get("message", "").strip()
    ts = item.get("timestamp", "")
    if any(k in msg for k in ["SETTLER", "Trade Executed", "WIN", "LOSS", "DAILY SUMMARY", "Active Trades"]):
        print(f"[{ts}] {msg}")
