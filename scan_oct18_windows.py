import urllib.request, urllib.parse, json, sys, time

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Split Oct 18 into 4-hour chunks so queries are fast and never timeout
windows = [
    ("2026-10-18T10:32:00Z", "2026-10-18T14:00:00Z"),
    ("2026-10-18T14:00:00Z", "2026-10-18T18:00:00Z"),
    ("2026-10-18T18:00:00Z", "2026-10-18T22:00:00Z"),
    ("2026-10-18T22:00:00Z", "2026-10-19T02:00:00Z"),
    ("2026-10-19T02:00:00Z", "2026-10-19T07:00:00Z"),
]

all_trades = []

for start, end in windows:
    print(f"Checking window: {start} -> {end}...", flush=True)
    end_cursor = end
    for _ in range(25):
        params = {
            "ownerId": OWNER_ID,
            "resource": SERVICE_ID,
            "direction": "backward",
            "limit": "100",
            "startTime": start,
            "endTime": end_cursor
        }
        url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
                logs = data.get("logs", [])
                if not logs:
                    break
                for item in logs:
                    ts = item.get("timestamp", "")
                    msg = item.get("message", "").strip()
                    if any(k in msg for k in ["[BG-SETTLER]", "TAKE_IT", "Trade Executed", "Bal:"]):
                        all_trades.append((ts, msg))
                        print(f"  [{ts[:19]}] {msg}", flush=True)
                nx = data.get("nextEndTime")
                if not nx or nx == end_cursor or nx < start:
                    break
                end_cursor = nx
                time.sleep(0.1)
        except Exception as e:
            print(f"  Err: {e}", flush=True)
            break

all_trades.sort(key=lambda x: x[0])
# Deduplicate
dedup = []
seen = set()
for t in all_trades:
    if t not in seen:
        seen.add(t)
        dedup.append(t)

print(f"\n================ TOTAL AUDIT ================")
print(f"Total relevant lines found: {len(dedup)}")
for ts, msg in dedup:
    print(f"[{ts[:19]}] {msg}")
