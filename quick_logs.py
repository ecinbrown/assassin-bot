import urllib.request, urllib.parse, json, sys
sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

params = {
    "ownerId": OWNER_ID,
    "resource": SERVICE_ID,
    "direction": "forward",
    "limit": "100",
    "startTime": "2026-10-03T10:08:10Z"
}
url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers={
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
    logs = data.get("logs", [])
    for item in logs:
        msg = item.get("message", "").strip()
        if "getUpdates" in msg:
            continue
        print(msg)
