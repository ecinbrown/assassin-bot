import urllib.request
import urllib.parse
import json
import sys
import time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

start_time = "2026-10-02T18:50:00Z"
all_events = []
seen = set()

page = 0
out_file = open("all_trade_events.txt", "w", encoding="utf-8")

while page < 80:  # safety cap
    params = {
        "ownerId": OWNER_ID,
        "resource": SERVICE_ID,
        "direction": "forward",
        "limit": "100",
        "startTime": start_time
    }
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json"
    })
    
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                print(f"Page {page}: No logs returned, done.")
                break
            
            new_events = 0
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                
                # Check for trade-related log items
                if any(k in msg for k in [
                    "[BG-SETTLER]", "Trade Executed", "TAKE_IT", 
                    "Active Strategy Mode", "Starting Bankroll",
                    "Portfolio:", "CRITICAL", "WIN", "LOSS", "Reset to Base"
                ]):
                    line = f"[{ts}] {msg}"
                    out_file.write(line + "\n")
                    out_file.flush()
                    all_events.append(line)
                    new_events += 1
            
            print(f"Page {page} ({logs[0]['timestamp'][:19]} -> {logs[-1]['timestamp'][:19]}): {len(logs)} logs, {new_events} events", flush=True)
            
            next_start = data.get("nextStartTime")
            if not next_start or next_start == start_time or not data.get("hasMore", True):
                print("End of log stream reached.")
                break
            start_time = next_start
            page += 1
            time.sleep(0.2)
    except Exception as e:
        print(f"Err on page {page}: {e}", flush=True)
        break

out_file.close()
print(f"\nDone! Found {len(all_events)} trade events saved to all_trade_events.txt", flush=True)
