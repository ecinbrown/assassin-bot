import asyncio
import websockets
import json
import logging
import time

logger = logging.getLogger(__name__)

async def start_wss_listener(wss_url: str, auth_payload: str, tick_queue: asyncio.Queue, out_queue: asyncio.Queue = None):
    """
    Connects to the WSS and listens for raw tick data.
    Also processes outgoing WSS messages if out_queue is provided.
    """
    logger.info(f"Starting WSS connection to {wss_url}...")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Origin": "https://pocketoption.com"
        }
        
        async with websockets.connect(wss_url, extra_headers=headers) as websocket:
            logger.info("WSS Connected. Sending authentication payload...")
            
            await websocket.send(auth_payload)
            
            asyncio.create_task(keep_alive(websocket))
            if out_queue:
                asyncio.create_task(process_out_queue(websocket, out_queue))
            
            while True:
                message = await websocket.recv()
                
                if isinstance(message, bytes):
                    message = message.decode('utf-8')
                
                logger.info(f"RAW WSS: {message[:100]}")
                
                if message.startswith('42'):
                    try:
                        data_arr = json.loads(message[2:]) 
                        event_type = data_arr[0]
                        event_data = data_arr[1] if len(data_arr) > 1 else {}
                        
                        logger.info(f"WSS Event: {event_type}")
                        
                        if event_type == "updateStream" or event_type == "tick":
                            symbol = event_data.get('symbol', 'UNKNOWN')
                            price = event_data.get('price', 0.0)
                            timestamp = event_data.get('time', time.time())
                            
                            if price > 0:
                                await tick_queue.put({
                                    'symbol': symbol,
                                    'price': price,
                                    'timestamp': timestamp
                                })
                                
                    except json.JSONDecodeError:
                        pass
                    except Exception as e:
                        logger.error(f"Error parsing message: {e}")
                        
    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"WSS Connection closed: {e}")
    except Exception as e:
        logger.error(f"WSS Error: {e}")

async def keep_alive(websocket):
    """Sends Socket.IO '2' ping every 25 seconds."""
    while True:
        await asyncio.sleep(25)
        try:
            await websocket.send('2')
        except websockets.exceptions.ConnectionClosed:
            break

async def process_out_queue(websocket, out_queue: asyncio.Queue):
    """Listens for outgoing WSS payloads and sends them over the active websocket."""
    while True:
        try:
            msg = await out_queue.get()
            logger.info(f"WSS OUTGOING: sending {msg[:50]}...")
            await websocket.send(msg)
            out_queue.task_done()
        except websockets.exceptions.ConnectionClosed:
            logger.error("out_queue_processor: Connection closed, stopping.")
            break
        except Exception as e:
            logger.error(f"Error sending WSS message: {e}")

