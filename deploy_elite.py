import urllib.request, json, sys
sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SVC_ID = "srv-d820d5rtqb8s73c4t39g"

def api(path, method="GET", body=None):
    url = f"https://api.render.com/v1{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

# Ensure BASE_STAKE is 1.0 flat
for key, value in [
    ("INITIAL_BALANCE", "15.62"),
    ("BASE_STAKE", "1.0")
]:
    s, r = api(f"/services/{SVC_ID}/env-vars/{key}", "PUT", {"value": value})
    if s == 200:
        print(f"Updated {key}={value}", flush=True)
    else:
        s2, r2 = api(f"/services/{SVC_ID}/env-vars", "POST", {"key": key, "value": value})
        print(f"Create {key}={value}: status={s2}", flush=True)

# Trigger deploy
print("\nTriggering clean deploy without any restrictions...", flush=True)
s, r = api(f"/services/{SVC_ID}/deploys", "POST", {"clearCache": "do_not_clear"})
print(f"Deploy response status: {s}", flush=True)
if isinstance(r, dict):
    d = r.get('deploy', r)
    print(f"Deploy ID: {d.get('id', 'n/a')}", flush=True)
    print(f"Deploy status: {d.get('status', 'n/a')}", flush=True)
else:
    print(f"Response: {r}", flush=True)
