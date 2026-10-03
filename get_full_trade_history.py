import urllib.request
import urllib.parse
import json
import sys

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

out_f = open("trades_dump.txt", "w", encoding="utf-8")
end_time = None
all_logs = []
seen = set()

for p in range(12):
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            print(f"Page {p}: got {len(logs)} logs", flush=True)
            if not logs:
                break
            for item in logs:
                msg = item.get("message", "").strip()
                ts = item.get("timestamp", "")
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                all_logs.append((ts, msg))
            next_end = data.get("nextEndTime")
            if not next_end or next_end == end_time:
                break
            end_time = next_end
    except Exception as e:
        print(f"Err p{p}: {e}", flush=True)
        break

all_logs.sort(key=lambda x: x[0])
print(f"Total collected: {len(all_logs)}", flush=True)

for ts, msg in all_logs:
    if any(k in msg for k in [
        "[SCORECARD]", "SEQ LOSS", "SEQ WIN", "Trade Executed", 
        "SIMULATION TRADE", "TAKE_IT", "Active Strategy Mode", 
        "Balance:", "Gale", "WON", "LOST", "SETTLER", "Starting Bankroll",
        "Config loaded", "Portfolio:", "CRITICAL", "WIN", "LOSS"
    ]):
        out_f.write(f"[{ts}] {msg}\n")

out_f.close()
print("Saved to trades_dump.txt", flush=True)
