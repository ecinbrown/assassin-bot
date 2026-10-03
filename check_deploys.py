import urllib.request
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

req = urllib.request.Request(
    f"https://api.render.com/v1/services/{SERVICE_ID}/deploys?limit=5",
    headers={"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
)
with urllib.request.urlopen(req) as resp:
    deploys = json.loads(resp.read().decode())
    for d in deploys:
        dep = d["deploy"]
        print(f"Deploy ID: {dep['id']}, Status: {dep['status']}, Created: {dep['createdAt']}, Finished: {dep.get('finishedAt')}")
