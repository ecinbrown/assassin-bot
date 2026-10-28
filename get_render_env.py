import urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

req = urllib.request.Request(
    f"https://api.render.com/v1/services/{SERVICE_ID}/env-vars",
    headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
)
data = json.loads(urllib.request.urlopen(req).read().decode())
for item in data:
    ev = item.get("envVar", {})
    k = ev.get("key")
    v = ev.get("value")
    # Hide private key for safety
    if "KEY" in k or "TOKEN" in k or "SECRET" in k:
        v = v[:6] + "..." if v else ""
    print(f"{k} = {v}")
