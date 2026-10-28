import time, urllib.request, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
SID = "srv-d820d5rtqb8s73c4t39g"

for i in range(20):
    time.sleep(10)
    req = urllib.request.Request(f"https://api.render.com/v1/services/{SID}/deploys?limit=1", headers={"Authorization": f"Bearer {API_KEY}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
            dep = data[0].get('deploy', {})
            status = dep.get('status')
            print(f"[{i+1}] Deploy {dep.get('id')}: {status}", flush=True)
            if status == "live":
                print("Deploy is LIVE!", flush=True)
                break
    except Exception as e:
        print("Error checking status:", e, flush=True)
