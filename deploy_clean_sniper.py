import urllib.request, json, sys, time, subprocess

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# 1. Update STRATEGY_MODE to 10TPD on Render
print("--> Updating Render STRATEGY_MODE to 10TPD...", flush=True)
url = f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars"
payload = [
    {"key": "STRATEGY_MODE", "value": "10TPD"}
]
req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode('utf-8'),
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    },
    method="PUT"
)

try:
    with urllib.request.urlopen(req) as resp:
        print(f"Env var updated successfully! Status: {resp.status}", flush=True)
except Exception as e:
    print(f"Error updating env vars: {e}", flush=True)

# 2. Git add and commit
print("--> Git adding and committing clean sniper configs...", flush=True)
subprocess.run(["git", "add", "main.py", 
                "assassin_strategy/nogale_sniper_clean_config.json", 
                "assassin_strategy/nogale_84pct_12tpd_config.json", 
                "assassin_strategy/nogale_80pct_20tpd_config.json"], check=True)

subprocess.run(["git", "commit", "-m", "fix: purge weak WILLR and sub-2.0 BB setups; lock in 85.7% clean sniper 10TPD config"], check=True)

# 3. Git push
print("--> Pushing to GitHub...", flush=True)
subprocess.run(["git", "push", "origin", "main"], check=True)

# 4. Trigger fresh deployment
print("--> Triggering fresh deploy on Render...", flush=True)
deploy_url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys"
deploy_req = urllib.request.Request(
    deploy_url,
    data=json.dumps({"clearCache": "clear"}).encode('utf-8'),
    headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    },
    method="POST"
)

dep_id = None
try:
    with urllib.request.urlopen(deploy_req) as resp:
        res = json.loads(resp.read().decode())
        dep_id = res.get("id")
        print(f"Deploy triggered! Deploy ID: {dep_id}", flush=True)
except Exception as e:
    print(f"Error triggering deploy: {e}", flush=True)

# 5. Monitor deploy status
if dep_id:
    print("--> Waiting for deployment to go live...", flush=True)
    status_url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys/{dep_id}"
    status_req = urllib.request.Request(
        status_url,
        headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
    )
    for _ in range(40):
        time.sleep(6)
        try:
            with urllib.request.urlopen(status_req) as resp:
                d = json.loads(resp.read().decode())
                status = d.get("status")
                print(f"Deploy status: {status}", flush=True)
                if status == "live":
                    print("Deploy is LIVE!", flush=True)
                    break
                elif status in ("build_failed", "update_failed", "canceled"):
                    print(f"Deploy failed with status: {status}", flush=True)
                    break
        except Exception as e:
            print(f"Error checking status: {e}", flush=True)
