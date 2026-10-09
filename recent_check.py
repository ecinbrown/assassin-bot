import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OID = "tea-d8204m7aqgkc738vou6g"
SID = "srv-d820d5rtqb8s73c4t39g"

end_time = None
results = []
seen = set()

for page in range(20):
    params = {"ownerId": OID, "resource": SID, "direction": "backward", "limit": "100"}
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
            for item in logs:
                ts = item.get("timestamp", "")
                msg = item.get("message", "").strip()
                if (ts, msg) in seen:
                    continue
                seen.add((ts, msg))
                if any(k in msg for k in [
                    "TAKE_IT", "SETTLER", "Trade Executed", "ERROR", "Error",
                    "Traceback", "exception", "CRITICAL", "WARNING",
                    "candle", "signal", "feed", "disconnect", "reconnect",
                    "Binance", "KEEP-ALIVE", "STRATEGY MODE"
                ]):
                    results.append((ts, msg))
            nx = data.get("nextEndTime")
            if not nx or nx == end_time:
                break
            end_time = nx
            time.sleep(0.4)
    except urllib.error.HTTPError as e:
        if e.code == 429:
            time.sleep(15)
            continue
        break
    except Exception as e:
        print(f"Error: {e}")
        break

results.sort(key=lambda x: x[0])

with open("recent_check.txt", "w", encoding="utf-8") as f:
    for ts, msg in results[-60:]:
        f.write(f"[{ts[:19]}] {msg}\n")
    f.write(f"\nTotal relevant lines found: {len(results)}\n")
    # Find last trade/signal
    last_trade = None
    last_settler = None
    for ts, msg in reversed(results):
        if "TAKE_IT" in msg and last_trade is None:
            last_trade = (ts, msg)
        if "SETTLER" in msg and last_settler is None:
            last_settler = (ts, msg)
        if last_trade and last_settler:
            break
    f.write(f"\nLast signal: {last_trade[0][:19] if last_trade else 'NONE FOUND'}\n")
    f.write(f"Last settlement: {last_settler[0][:19] if last_settler else 'NONE FOUND'}\n")

print(f"Done. {len(results)} lines. Check recent_check.txt")
