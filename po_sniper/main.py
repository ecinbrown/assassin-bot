import asyncio
import os
import logging
from dotenv import load_dotenv
from aiohttp import web

from logic_engine import LogicEngine
from browser_agent import BrowserAgent
from terminal_telegram import TerminalTelegramBot
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

async def handle_ping(request):
    return web.Response(text="Terminal Velocity Sniper Online! 🚀")

async def start_web_server(browser_agent, logic_engine):
    async def handle_telemetry(request):
        payout = getattr(browser_agent, 'last_known_payout', 85)
        pages = list(browser_agent.pages.values()) if hasattr(browser_agent, 'pages') else []
        sym = ", ".join(browser_agent.pages.keys()) if hasattr(browser_agent, 'pages') and browser_agent.pages else 'None'
        balance_str = "N/A"
        
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
    
    BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    if not BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN in environment. Bot cannot start.")
        return

    init_db()
    
    tick_queue = asyncio.Queue()
    logic_engine = LogicEngine(target_symbols=[])
    
    browser_agent = BrowserAgent(tick_queue=tick_queue, auth_state_path="auth_state.json", headless=True)
    
    telegram_bot = TerminalTelegramBot(BOT_TOKEN, logic_engine, browser_agent)
    logic_engine.notifier = telegram_bot

    logger.info("🚀 Booting Terminal Velocity Sniper (VIP 15m Engine + Playwright)...")
    
    try:
        await start_web_server(browser_agent, logic_engine)
        await telegram_bot.start_bot()
        await browser_agent.start()
        
        active_assets = await browser_agent.select_top_assets(max_assets=5, logic_engine=logic_engine)
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
            asyncio.create_task(safe_task("logic_engine", lambda: logic_engine.process_tick_stream(tick_queue, browser_agent))),
            asyncio.create_task(safe_task("tick_poller", lambda: browser_agent.poll_ticks())),
            asyncio.create_task(safe_task("payout_watchdog", lambda: browser_agent.payout_watchdog(logic_engine))),
        ]
        
        # USER REQUEST: "make sure watchdog doesnt restart page and cause errors it just need to find the element on the chart and look at it constantly"
        # The supervisor that used to aggressively restart the browser if ticks delayed has been REMOVED entirely.
        
        await asyncio.gather(*tasks)
        
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
    except Exception as e:
        logger.error(f"Fatal Error in main event loop: {e}")
    finally:
        try:
            await browser_agent.stop()
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
