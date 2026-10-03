import urllib.request, json

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
BASE = "https://api.render.com/v1"
SVC_ID = "srv-d820d5rtqb8s73c4t39g"  # homma-sniper = assassin-bot repo

def api_req(path, method="GET", data=None):
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(f"{BASE}{path}", data=body, method=method, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    })
    try:
        resp = urllib.request.urlopen(req)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  HTTP {e.code}: {body}")
        return None

# 1. Get current env vars
print("=== CURRENT ENV VARS ===")
envs = api_req(f"/services/{SVC_ID}/env-vars")
if envs:
    for ev in envs:
        e = ev.get("envVar", ev)
        name = e.get("key", "?")
        val = e.get("value", "?")
        if any(x in name.upper() for x in ("KEY", "TOKEN", "SECRET", "PRIVATE")):
            print(f"  {name} = ***REDACTED***")
        else:
            print(f"  {name} = {val}")

# 2. Update STRATEGY_MODE
print("\n=== SETTING STRATEGY_MODE=GALE1_88PCT ===")
# Try PUT first (update existing)
result = api_req(f"/services/{SVC_ID}/env-vars/STRATEGY_MODE", "PUT", {"value": "GALE1_88PCT"})
if result:
    print("  Updated existing STRATEGY_MODE")
else:
    # Try POST (create new)
    print("  Trying to create new env var...")
    result = api_req(f"/services/{SVC_ID}/env-vars", "POST", [{"key": "STRATEGY_MODE", "value": "GALE1_88PCT"}])
    if result:
        print("  Created STRATEGY_MODE = GALE1_88PCT")
    else:
        print("  FAILED to set env var")

# 3. Trigger deploy
print("\n=== TRIGGERING DEPLOY ===")
result = api_req(f"/services/{SVC_ID}/deploys", "POST", {})
if result:
    dep = result.get("deploy", result)
    print(f"  Deploy ID: {dep.get('id', 'N/A')}")
    print(f"  Status: {dep.get('status', 'N/A')}")
    print(f"  Commit: {dep.get('commit', {}).get('message', 'N/A')}")
else:
    print("  Deploy trigger failed, but git push auto-deploy should handle it.")

print("\nDone!")
