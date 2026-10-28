import urllib.request, urllib.parse, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

params = {
    'ownerId': OWNER_ID,
    'resource': SERVICE_ID,
    'direction': 'backward',
    'limit': 500
}
url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        logs = data.get("logs", [])
        print(f"Total log entries retrieved: {len(logs)}")
        trade_events = []
        for item in reversed(logs):
            msg = item.get("message", "").strip()
            ts = item.get("timestamp", "")[:19]
            if any(k in msg for k in ["SETTLER", "TRADE OPENED", "WIN", "LOSS", "ORDER", "Scorecard", "Bal:"]):
                if "Candle Closed" not in msg:
                    print(f"[{ts}] {msg}")
                    trade_events.append((ts, msg))
        if not trade_events:
            print("No settlement/trade events in window.")
except Exception as e:
    print(f"Error: {e}")
