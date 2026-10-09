import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"
end_time = None
all_trades = []
seen = set()

for page in range(50):
    params = {"ownerId": OWNER_ID, "resource": SERVICE_ID, "direction": "backward", "limit": "100"}
    if end_time:
        params["endTime"] = end_time
    url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            logs = data.get("logs", [])
            if not logs:
                break
            new = 0
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                key = (ts, msg)
                if key not in seen:
                    seen.add(key)
                    if any(k in msg for k in ["SETTLER", "SIMULATION TRADE", "Starting Bankroll", "Bal:", "TAKE_IT", "Starting balance", "initial_balance", "INITIAL_BALANCE"]):
                        all_trades.append((ts, msg))
                    new += 1
            if new == 0:
                break
            nx = data.get("nextEndTime")
            if not nx or nx == end_time:
                break
            end_time = nx
    except urllib.error.HTTPError as e:
        if e.code == 429:
            sys.stderr.write(f"Rate limited at page {page}, waiting 10s...\n")
            time.sleep(10)
            continue
        all_trades.append(("ERROR", str(e)))
        break
    except Exception as e:
        all_trades.append(("ERROR", str(e)))
        break
    time.sleep(0.3)

all_trades.sort(key=lambda x: x[0])

out = "trade_full_results.txt"
with open(out, "w", encoding="utf-8") as f:
    for ts, msg in all_trades:
        f.write(f"[{ts}] {msg}\n")
    f.write(f"\nTotal trade lines: {len(all_trades)}\n")
    wins = sum(1 for _, m in all_trades if "WIN" in m and "SETTLER" in m)
    losses = sum(1 for _, m in all_trades if "LOSS" in m and "SETTLER" in m)
    f.write(f"Wins: {wins}, Losses: {losses}\n")
    for ts, msg in reversed(all_trades):
        if "Bal:" in msg:
            bal = msg.split("Bal:")[1].strip()
            f.write(f"Current Balance: {bal}\n")
            break

print(f"Done. {len(all_trades)} lines -> {out}")
