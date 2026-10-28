import urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# 1. Update STRATEGY_MODE to 20TPD
print("Updating STRATEGY_MODE to 20TPD...", flush=True)
url = f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars"
payload = [
    {"key": "STRATEGY_MODE", "value": "20TPD"}
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
        print("Env var updated successfully! Status:", resp.status)
except Exception as e:
    print("Error updating env vars:", e)

# 2. Trigger fresh deployment
print("Triggering fresh deploy...", flush=True)
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

try:
    with urllib.request.urlopen(deploy_req) as resp:
        res = json.loads(resp.read().decode())
        print("Deploy triggered! Deploy ID:", res.get("id"))
except Exception as e:
    print("Error triggering deploy:", e)
