import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Start from where the previous scan left off
start_time = "2026-10-03T04:25:00Z"
all_events = []
seen = set()
page = 0

while page < 80:
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
                break
            
            new_events = 0
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                
                if any(k in msg for k in [
                    "[BG-SETTLER]", "Trade Executed", "TAKE_IT", 
                    "Starting Bankroll", "STRATEGY MODE", "Bal:"
                ]):
                    line = f"[{ts}] {msg}"
                    all_events.append(line)
                    new_events += 1
            
            print(f"Page {page}: {len(logs)} logs, {new_events} events", flush=True)
            
            next_start = data.get("nextStartTime")
            if not next_start or next_start == start_time or not data.get("hasMore", True):
                break
            start_time = next_start
            page += 1
            time.sleep(0.3)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"Rate limited at page {page}, waiting 15s...", flush=True)
            time.sleep(15)
            continue
        print(f"HTTP Error: {e}", flush=True)
        break
    except Exception as e:
        print(f"Error: {e}", flush=True)
        break

with open("trades_oct3_to_now.txt", "w", encoding="utf-8") as f:
    for line in all_events:
        f.write(line + "\n")

# Summary
wins = sum(1 for l in all_events if "WIN" in l and "SETTLER" in l)
losses = sum(1 for l in all_events if "LOSS" in l and "SETTLER" in l)
trades = sum(1 for l in all_events if "Trade Executed" in l)

print(f"\nTotal events: {len(all_events)}")
print(f"Trades executed: {trades}")
print(f"Wins: {wins}, Losses: {losses}")

# Find last balance
for line in reversed(all_events):
    if "Bal:" in line:
        bal = line.split("Bal:")[1].strip()
        print(f"Latest Balance: {bal}")
        break

print("Saved to trades_oct3_to_now.txt")
