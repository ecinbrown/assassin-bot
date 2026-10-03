import urllib.request
import urllib.parse
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

end_time = None
all_logs = []
seen_timestamps = set()

for page in range(25):
    params = {
        "ownerId": OWNER_ID,
        "resource": SERVICE_ID,
        "direction": "backward",
        "limit": "100"
    }
    if end_time:
        params["endTime"] = end_time
    
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json"
    })

    
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            print(f"Page {page}: fetched {len(logs)} logs", flush=True)
            if not logs:
                break
            
            new_logs = 0
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                key = (ts, msg)
                if key not in seen_timestamps:
                    seen_timestamps.add(key)
                    all_logs.append((ts, msg))
                    new_logs += 1
            
            if new_logs == 0:
                print(f"Page {page}: No new logs, stopping.", flush=True)
                break
                
            next_end = data.get("nextEndTime")
            if not next_end or next_end == end_time:
                break
            end_time = next_end
    except Exception as e:
        print(f"Error on page {page}: {e}", flush=True)
        break

print(f"Total unique logs collected: {len(all_logs)}", flush=True)
all_logs.sort(key=lambda x: x[0])

print("\n=== RELEVANT BOT EVENTS ===", flush=True)
for ts, msg in all_logs:
    if any(k in msg for k in [
        "[SCORECARD]", "SEQ LOSS", "SEQ WIN", "Trade Executed", 
        "SIMULATION TRADE", "TAKE_IT", "Active Strategy Mode", 
        "Balance:", "Gale", "WON", "LOST", "SETTLER", "Starting Bankroll",
        "Config loaded", "Portfolio:", "CRITICAL", "WIN", "LOSS", "WIN-RATE"
    ]):
        print(f"[{ts}] {msg}", flush=True)

