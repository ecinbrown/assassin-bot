import asyncio
import os
import logging
from dotenv import load_dotenv
from aiohttp import web

from logic_engine import LogicEngine
from wss_agent import WSSAgent
from terminal_telegram import TerminalTelegramBot
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def handle_ping(request):
    return web.Response(text="Terminal Velocity Sniper Online! 🚀")

async def start_web_server(wss_agent, logic_engine):
    async def handle_telemetry(request):
        payout = getattr(wss_agent, 'last_known_payout', 92)
        sym = ", ".join(wss_agent.pages.keys()) if hasattr(wss_agent, 'pages') and wss_agent.pages else 'None'
        balance_str = f"${wss_agent.demo_balance:.2f}" if hasattr(wss_agent, 'demo_balance') else "N/A"
        
        return web.json_response({
            "status": "running" if not logic_engine.paused else "stopped",
            "balance": balance_str,
            "active_asset": sym,
            "current_payout": payout,
            "risk_strategy": "Kelly Optimal"
        })

    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    app.router.add_get('/telemetry', handle_telemetry)
    
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"🌐 Keep-Alive Web Server listening on port {port}")

async def main():
    load_dotenv()
    
    BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '7771345334:AAGGgOoC24R-kqK5mFIgQF1r_enX3XiP0Wk')
    if not BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN in environment. Bot cannot start.")
        return

    init_db()
    
    tick_queue = asyncio.Queue()
    logic_engine = LogicEngine(target_symbols=[])
    
    # Use pure WebSocket agent — NO Chromium, NO captcha, NO memory issues
    wss_agent = WSSAgent(tick_queue=tick_queue)
    
    telegram_bot = TerminalTelegramBot(BOT_TOKEN, logic_engine, wss_agent)
    logic_engine.notifier = telegram_bot

    logger.info("🚀 Booting Terminal Velocity Sniper (Pure WebSocket Mode — NO BROWSER)...")
    logger.info("   RAM Usage: ~30MB (vs ~800MB with Playwright)")
    
    try:
        await start_web_server(wss_agent, logic_engine)
        await telegram_bot.start_bot()
        
        # Start WebSocket connection (non-blocking — runs in background)
        wss_task = asyncio.create_task(wss_agent.start())
        
        # Wait a few seconds for auth to complete
        await asyncio.sleep(8)
        
        # Select top assets
        active_assets = await wss_agent.select_top_assets(max_assets=5, logic_engine=logic_engine)
        if active_assets:
            logic_engine.target_symbols = active_assets
        else:
            logger.warning("No high-payout assets available on boot. Pausing engine.")
            logic_engine.paused = True
        
        async def safe_task(name, coro_factory):
            while True:
                try:
                    await coro_factory()
                    break
                except asyncio.CancelledError:
                    logger.info(f"Task '{name}' cancelled.")
                    break
                except Exception as e:
                    logger.error(f"Task '{name}' crashed: {e}. Restarting in 5s...")
                    await asyncio.sleep(5)
        
        tasks = [
            wss_task,
            asyncio.create_task(safe_task("logic_engine", lambda: logic_engine.process_tick_stream(tick_queue, wss_agent))),
            asyncio.create_task(safe_task("heartbeat", lambda: wss_agent.poll_ticks())),
            asyncio.create_task(safe_task("payout_watchdog", lambda: wss_agent.payout_watchdog(logic_engine))),
        ]
        
        await asyncio.gather(*tasks)
        
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Fatal Error in main event loop: {e}")
    finally:
        try:
            await wss_agent.stop()
        except:
            pass

def run():
    import time as _time
    crash_count = 0
    while True:
        try:
            asyncio.run(main())
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            crash_count += 1
            wait = min(10 * crash_count, 60)
            print(f"💀 FATAL CRASH #{crash_count}: {e}. Restarting in {wait}s...")
            _time.sleep(wait)

if __name__ == "__main__":
    run()
