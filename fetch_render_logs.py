import urllib.request
import json
import sys

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

sys.stdout.reconfigure(encoding='utf-8')

limit = 100
if len(sys.argv) > 1:
    limit = int(sys.argv[1])

url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&direction=backward&limit=100"
headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json"
}

all_trade_logs = []
seen_ids = set()

for page in range(10): # up to 1000 lines
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                break
            for item in logs:
                msg = item.get("message", "")
                ts = item.get("timestamp", "")
                if any(k in msg for k in ["[TRADE]", "[SCORECARD]", "SEQ LOSS", "SEQ WIN", "Trade Executed", "SIMULATION TRADE", "TAKE_IT", "Active Strategy Mode", "Balance:"]):
                    all_trade_logs.append(f"[{ts}] {msg.strip()}")
            if not data.get("hasMore"):
                break
            next_start = data.get("nextStartTime")
            if not next_start:
                break
            url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&direction=backward&limit=100&startTime={next_start}"
    except Exception as e:
        print(f"Error on page {page}: {e}")
        break

print(f"Found {len(all_trade_logs)} trade-related log entries:")
for l in reversed(all_trade_logs):
    print(l)


