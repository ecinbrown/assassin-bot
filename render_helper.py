import os
import json
import urllib.request
import sys

API_KEY = os.environ.get("RENDER_API_KEY", "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5")
OWNER_ID = "tea-d8204m7aqgkc738vou6g"
SERVICE_ID = "srv-d820d5rtqb8s73c4t39g"

def get_render_logs(limit=50):
    url = f"https://api.render.com/v1/logs?ownerId={OWNER_ID}&resource={SERVICE_ID}&direction=backward&limit={limit}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [e.get("message", "").strip() for e in reversed(data.get("logs", []))]
    except Exception as e:
        return [f"Error fetching Render logs: {e}"]

def trigger_render_deploy():
    url = f"https://api.render.com/v1/services/{SERVICE_ID}/deploys"
    req = urllib.request.Request(url, data=b"{}", headers={
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for line in get_render_logs(30):
        print(line)
