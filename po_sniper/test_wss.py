import asyncio
import websockets
import json

async def test():
    url = "wss://api-eu.po.market/socket.io/?EIO=4&transport=websocket"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Origin": "https://pocketoption.com"
    }
    
    with open("auth_state.json", "r") as f:
        d = json.load(f)
        session = [c["value"] for c in d["cookies"] if c["name"] == "ci_session"][0]
        
    headers["Cookie"] = f"ci_session={session}"
    
    async with websockets.connect(url, extra_headers=headers) as ws:
        print("Connected. Waiting for 0...")
        msg0 = await ws.recv()
        print("RECV:", msg0)
        
        print("Sending 40...")
        await ws.send('40')
        
        try:
            for _ in range(5):
                msg = await ws.recv()
                print("RECV:", msg[:200])
        except Exception as e:
            print("Error:", e)

asyncio.run(test())
