import urllib.request, urllib.parse, json, sys, time
from collections import Counter

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OID = "tea-d8204m7aqgkc738vou6g"
SID = "srv-d820d5rtqb8s73c4t39g"

st = "2026-10-05T00:00:00Z"
trades = []
seen = set()
p = 0

while p < 80:
    params = {"ownerId": OID, "resource": SID, "direction": "forward", "limit": "100", "startTime": st}
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                break
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                if "BG-SETTLER" in msg or "Trade Executed" in msg:
                    trades.append((ts, msg))
            nx = data.get("nextStartTime")
            if not nx or nx == st:
                break
            st = nx
            p += 1
            time.sleep(0.3)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(15)
            continue
        break
    except:
        break

trades.sort(key=lambda x: x[0])

day_counts = Counter()
day_wins = Counter()
day_losses = Counter()

for ts, msg in trades:
    day = ts[:10]
    if "Trade Executed" in msg:
        day_counts[day] += 1
    if "WIN" in msg and "SETTLER" in msg:
        day_wins[day] += 1
    if "LOSS" in msg and "SETTLER" in msg:
        day_losses[day] += 1

with open("daily_breakdown.txt", "w", encoding="utf-8") as f:
    for day in sorted(set(list(day_counts.keys()) + list(day_wins.keys()) + list(day_losses.keys()))):
        w = day_wins[day]
        l = day_losses[day]
        t = day_counts[day]
        wr = (w / (w + l) * 100) if (w + l) > 0 else 0
        line = f"{day}: {t} trades | {w}W / {l}L | WR: {wr:.0f}%"
        f.write(line + "\n")
        print(line, flush=True)
    
    total_t = sum(day_counts.values())
    total_w = sum(day_wins.values())
    total_l = sum(day_losses.values())
    total_wr = (total_w / (total_w + total_l) * 100) if (total_w + total_l) > 0 else 0
    summary = f"\nTotal: {total_t} trades | {total_w}W / {total_l}L | WR: {total_wr:.0f}%"
    f.write(summary + "\n")
    print(summary, flush=True)

    # Also dump individual trades
    f.write("\n=== ALL TRADES ===\n")
    for ts, msg in trades:
        f.write(f"[{ts[:19]}] {msg}\n")

print("Saved to daily_breakdown.txt")
