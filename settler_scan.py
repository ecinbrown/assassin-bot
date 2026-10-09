import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Only search for SETTLER lines (win/loss results) to minimize noise
# Scan backward to get the most recent data first
end_time = None
settlers = []
seen = set()

for page in range(30):
    params = {"ownerId": OWNER_ID, "resource": SERVICE_ID, "direction": "backward", "limit": "100"}
    if end_time:
        params["endTime"] = end_time
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                break
            new = 0
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                if "BG-SETTLER" in msg:
                    settlers.append((ts, msg))
                    new += 1
            nx = data.get("nextEndTime")
            if not nx or nx == end_time:
                break
            end_time = nx
            time.sleep(0.3)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(15)
            continue
        break
    except:
        break

settlers.sort(key=lambda x: x[0])

wins = 0
losses = 0
with open("settler_summary.txt", "w", encoding="utf-8") as f:
    for ts, msg in settlers:
        is_win = "WIN" in msg
        is_loss = "LOSS" in msg
        if is_win: wins += 1
        if is_loss: losses += 1
        tag = "W" if is_win else "L"
        f.write(f"[{tag}] [{ts[:19]}] {msg}\n")
    
    wr = (wins/(wins+losses)*100) if (wins+losses) > 0 else 0
    f.write(f"\n=== SUMMARY ===\n")
    f.write(f"Total settled: {wins+losses}\n")
    f.write(f"Wins: {wins} | Losses: {losses}\n")
    f.write(f"Win Rate: {wr:.1f}%\n")
    
    # Get balances
    for ts, msg in reversed(settlers):
        if "Bal:" in msg:
            bal = msg.split("Bal:")[1].strip()
            f.write(f"Latest Balance: {bal}\n")
            break

print(f"Done: {wins}W/{losses}L ({wr:.1f}%) -> settler_summary.txt")
