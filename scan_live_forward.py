import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

start_time = "2026-10-18T10:32:00Z"
events = []
seen = set()

print(f"Scanning logs starting from {start_time} forward...", flush=True)

page = 0
while page < 100:
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
                print("No more logs returned.", flush=True)
                break
            
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                if any(k in msg for k in ["[BG-SETTLER]", "TAKE_IT", "Trade Executed", "LOSS", "WIN", "Bal:"]):
                    events.append((ts, msg))
                    print(f"  >>> [{ts[:19]}] {msg}", flush=True)
            
            next_start = data.get("nextStartTime")
            if not next_start or next_start == start_time or not data.get("hasMore", True):
                print(f"Page {page}: Reached end of stream.", flush=True)
                break
            start_time = next_start
            page += 1
            if page % 10 == 0:
                print(f"Scanned {page} pages (up to {logs[-1]['timestamp'][:19]})...", flush=True)
            time.sleep(0.1)
    except Exception as e:
        print(f"Error on page {page}: {e}", flush=True)
        break

print(f"\n================ SUMMARY ================", flush=True)
print(f"Total trade events found: {len(events)}", flush=True)
wins = 0
losses = 0
for ts, msg in events:
    if "[BG-SETTLER]" in msg:
        if "WIN" in msg: wins += 1
        if "LOSS" in msg: losses += 1

print(f"Settled Trades: {wins + losses} (Wins: {wins}, Losses: {losses})", flush=True)
if (wins + losses) > 0:
    print(f"Live Win Rate: {wins/(wins+losses)*100:.1f}%", flush=True)

with open("live_trades_since_deploy.txt", "w", encoding="utf-8") as f:
    for ts, msg in events:
        f.write(f"[{ts}] {msg}\n")
