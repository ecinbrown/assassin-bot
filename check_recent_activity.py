import urllib.request, urllib.parse, json, sys
sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

params = {
    "ownerId": OWNER_ID,
    "resource": SERVICE_ID,
    "direction": "backward",
    "limit": "50"
}
url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers={
    "Accept": "application/json",
    "Authorization": f"Bearer {API_KEY}"
})

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode('utf-8'))
        lines = []
        if isinstance(data, list):
            lines = [item.get("message", "") for item in data]
        elif isinstance(data, dict):
            lines = [item.get("message", "") for item in data.get("logs", [])]
        for line in reversed(lines):
            if any(k in line for k in ["TRADE", "SIGNAL", "SETTLE", "WIN", "LOSS", "PAUSE", "CIRCUIT", "BALANCE", "ERROR"]):
                print(line)
        print(f"Total log lines inspected: {len(lines)}")
        if lines:
            print("Last line:", lines[0] if lines else "None")
except Exception as e:
    print(f"Error: {e}")
