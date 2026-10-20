import urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

# Update INITIAL_BALANCE to 15 and STRATEGY_MODE to CONFLUENCE
updates = [
    {"key": "INITIAL_BALANCE", "value": "15"},
    {"key": "STRATEGY_MODE", "value": "CONFLUENCE"},
]

for env in updates:
    payload = json.dumps({"value": env["value"]}).encode()
    url = f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars/{env['key']}"
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }, method="PUT")
    try:
        resp = urllib.request.urlopen(req)
        print(f"✅ Updated {env['key']} = {env['value']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"❌ Failed {env['key']}: {e.code} {body}")
