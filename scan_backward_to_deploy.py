import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

DEPLOY_TIME = "2026-10-22T01:38:00Z"
events = []
seen = set()
end_time = None

print(f"Scanning backward from now until deploy ({DEPLOY_TIME})...", flush=True)

page = 0
reached_deploy = False

while page < 300 and not reached_deploy:
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
        with urllib.request.urlopen(req, timeout=35) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                print("No more logs.", flush=True)
                break
            
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if ts < DEPLOY_TIME:
                    reached_deploy = True
                    break
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                if any(k in msg for k in ["[BG-SETTLER]", "TAKE_IT", "Trade Executed", "Bal:"]):
                    events.append((ts, msg))
                    print(f"  >>> [{ts[:19]}] {msg}", flush=True)

            nx = data.get("nextEndTime")
            if not nx or nx == end_time:
                break
            end_time = nx
            page += 1
            if page % 15 == 0:
                print(f"Page {page}: at {end_time[:19]} ({len(events)} events found)...", flush=True)
            time.sleep(0.15)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print("Rate limit 429, sleeping 5s...", flush=True)
            time.sleep(5)
            continue
        print(f"HTTP Err: {e}", flush=True)
        time.sleep(2)
        continue
    except Exception as e:
        print(f"Err ({e}), retrying in 2s...", flush=True)
        time.sleep(2)
        continue

events.sort(key=lambda x: x[0])

print(f"\n================ FULL AUDIT SINCE DEPLOY ================", flush=True)
print(f"Scanned {page} pages backward to {DEPLOY_TIME}")
print(f"Total trade events: {len(events)}")

wins = 0
losses = 0
for ts, msg in events:
    if "[BG-SETTLER]" in msg:
        if "WIN" in msg: wins += 1
        if "LOSS" in msg: losses += 1

total = wins + losses
print(f"Settled Trades: {total} (Wins: {wins}, Losses: {losses})")
if total > 0:
    print(f"Win Rate: {wins/total*100:.1f}%")

with open("full_deploy_trades.txt", "w", encoding="utf-8") as f:
    for ts, msg in events:
        f.write(f"[{ts}] {msg}\n")
print("Saved to full_deploy_trades.txt")
