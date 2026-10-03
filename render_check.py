import urllib.request, json

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
BASE = "https://api.render.com/v1"

def api_get(path):
    req = urllib.request.Request(f"{BASE}{path}", headers={
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json"
    })
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())

services = api_get("/services?limit=20")
for s in services:
    svc = s["service"]
    repo = svc.get("repo", "N/A")
    print(f"ID: {svc['id']}")
    print(f"  Name: {svc['name']}")
    print(f"  Repo: {repo}")
    print(f"  Type: {svc['type']}")
    print(f"  Branch: {svc.get('branch', 'N/A')}")
    print()
