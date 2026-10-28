import urllib.request, urllib.parse, json, sys

sys.stdout.reconfigure(encoding='utf-8')
API_KEY = "rnd_RK9uAeVwLLn32mgrpbBJCVl9ouT5"
OID = "tea-d8204m7aqgkc738vou6g"
SID = "srv-d820d5rtqb8s73c4t39g"

params = {'ownerId': OID, 'resource': SID, 'direction': 'backward', 'limit': '250'}
url = f"https://api.render.com/v1/logs?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers={'Authorization': f'Bearer {API_KEY}'})
try:
    with urllib.request.urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode())
        logs = data.get('logs', [])
        for item in reversed(logs):
            ts = item.get('timestamp', '')[:19]
            msg = item.get('message', '').strip()
            if any(k in msg for k in ['STRATEGY MODE', 'Armed', 'PRELOAD', 'INITIAL_BALANCE', 'Telegram', 'Ready', 'CRITICAL', 'NO-GALE', 'AssassinBot']):
                print(f"[{ts}] {msg}")
except Exception as e:
    print(f"Error: {e}")
