import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
BASE = "https://api.render.com/v1"
SVC_ID = "srv-d820d5rtqb8s73c4t39g"

def api_get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={
        "Authorization": f"Bearer {API_KEY}", "Accept": "application/json"
    })
    return json.loads(urllib.request.urlopen(req).read())

# Deploy status
deploys = api_get(f"/services/{SVC_ID}/deploys?limit=3")
print("=== DEPLOY STATUS ===")
for d in deploys:
    dep = d["deploy"]
    commit_msg = ""
    if dep.get("commit"):
        commit_msg = dep["commit"].get("message", "")[:70]
    print(f"  Status: {dep['status']} | Created: {dep.get('createdAt','')[:19]}")
    print(f"  Commit: {commit_msg}")

# Live logs
print("\n=== LIVE LOGS (last 80 lines) ===")
try:
    # Render logs endpoint
    log_req = urllib.request.Request(
        f"{BASE}/services/{SVC_ID}/log-streams",
        headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
    )
    logs_raw = urllib.request.urlopen(log_req).read()
    print(f"Raw response: {logs_raw[:500]}")
except Exception as e:
    print(f"Log stream error: {e}")

# Try deploy logs instead
try:
    deploys2 = api_get(f"/services/{SVC_ID}/deploys?limit=1")
    dep_id = deploys2[0]["deploy"]["id"]
    log_req2 = urllib.request.Request(
        f"{BASE}/services/{SVC_ID}/deploys/{dep_id}/logs",
        headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
    )
    logs2 = json.loads(urllib.request.urlopen(log_req2).read())
    print(f"\nDeploy logs ({len(logs2)} entries):")
    for entry in logs2[-50:]:
        msg = entry.get("message", entry.get("text", str(entry)))
        ts = entry.get("timestamp", "")[:19]
        safe_msg = str(msg).encode("ascii", "replace").decode("ascii")[:120]
        print(f"[{ts}] {safe_msg}")
except Exception as e:
    print(f"Deploy log error: {e}")

