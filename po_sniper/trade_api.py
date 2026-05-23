import json
import time
import random

def create_order_payload(asset: str, amount: float, action: str, duration_sec: int = 5) -> str:
    """
    Constructs the exact Socket.io '42["openOrder", {...}]' string payload.
    Action must be "call" or "put".
    """
    # Create a moderately unique request ID
    request_id = int(time.time() * 1000) + random.randint(100, 999) 
    
    payload = {
        "asset": asset,
        "amount": amount,
        "action": action.lower(),
        "isDemo": 1,
        "requestId": request_id, 
        "optionType": 100,
        "time": duration_sec
    }
    
    # The PocketOption API uses the '42["openOrder", {payload}]' structure
    return f'42["openOrder",{json.dumps(payload)}]'
