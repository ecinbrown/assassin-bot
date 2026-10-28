import urllib.request, urllib.parse, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&direction=backward&limit=50"
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {API_KEY}', 'Accept': 'application/json'})
resp = urllib.request.urlopen(req)
data = json.loads(resp.read().decode())
logs = data.get('logs', [])
print(f"Fetched {len(logs)} logs.")
for item in reversed(logs):
    print(f"[{item.get('timestamp')}] {item.get('message', '').strip()}")
