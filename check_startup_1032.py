import urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&startTime=2026-10-19T07:03:55Z&endTime=2026-10-19T07:04:11Z&limit=100"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())
print(f"Total logs in startup window: {len(data.get('logs', []))}")
for item in reversed(data.get('logs', [])):
    print(f"[{item.get('timestamp')}] {item.get('message', '').strip()}")
