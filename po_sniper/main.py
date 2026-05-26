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
    return web.Response(text="Terminal Velocity Sniper Online! 🚀 (Pure WebSocket Mode)")

async def start_web_server(wss_agent, logic_engine):
    async def handle_telemetry(request):
        sym = ", ".join(wss_agent.pages.keys()) if wss_agent.pages else "None"
        return web.json_response({
            "status": "running" if not logic_engine.paused else "paused",
            "connected": wss_agent._authenticated,
            "balance": f"${wss_agent.demo_balance:.2f}",
            "active_assets": sym,
            "pairs_count": len(wss_agent.pages),
            "payouts_tracked": len(wss_agent._asset_payouts),
            "strategy": "VIP 15M Reversal (RSI75 + BB2.5σ)",
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
    logger.info(f"🌐 Web server on port {port}")

async def main():
    load_dotenv()

    BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '7771345334:AAGGgOoC24R-kqK5mFIgQF1r_enX3XiP0Wk')
    if not BOT_TOKEN:
        logger.error("Missing TELEGRAM_BOT_TOKEN!")
        return

    init_db()

    tick_queue = asyncio.Queue()
    logic_engine = LogicEngine(target_symbols=[])

    wss_agent = WSSAgent(tick_queue=tick_queue)
    wss_agent.MAX_PAIRS = 8  # Monitor 8 pairs

    telegram_bot = TerminalTelegramBot(BOT_TOKEN, logic_engine, wss_agent)
    logic_engine.notifier = telegram_bot

    logger.info("═" * 60)
    logger.info("  TERMINAL VELOCITY SNIPER — Pure WebSocket Mode")
    logger.info("  Strategy: VIP 15M Reversal (RSI75 + BB 2.5σ)")
    logger.info("  Pairs: 8 dynamic (any OTC >=92% payout)")
    logger.info("  Sizing: 34% of balance per trade")
    logger.info("  RAM: ~30MB (no Chromium)")
    logger.info("═" * 60)

    try:
        await start_web_server(wss_agent, logic_engine)
        await telegram_bot.start_bot()

        # Start WebSocket (runs in background)
        wss_task = asyncio.create_task(wss_agent.start())

        # Wait for auth before selecting assets
        for i in range(30):
            if wss_agent._authenticated:
                break
            await asyncio.sleep(1)

        if wss_agent._authenticated:
            active = await wss_agent.select_top_assets(max_assets=8, logic_engine=logic_engine)
            if active:
                logic_engine.target_symbols = active
                logger.info(f"✅ Engine armed with {len(active)} pairs")
            else:
                logger.warning("No assets found. Engine will start when pairs are available.")
        else:
            logger.warning("Auth pending. Send /token in Telegram or check PO_SESSION_TOKEN env var.")
            # Still select defaults so the engine has something
            active = await wss_agent.select_top_assets(max_assets=8, logic_engine=logic_engine)
            logic_engine.target_symbols = active if active else []

        async def safe_loop(name, coro_fn):
            while True:
                try:
                    await coro_fn()
                    break
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Task '{name}' crashed: {e}. Restarting in 5s...")
                    await asyncio.sleep(5)

        await asyncio.gather(
            wss_task,
            asyncio.create_task(safe_loop("logic", lambda: logic_engine.process_tick_stream(tick_queue, wss_agent))),
            asyncio.create_task(safe_loop("heartbeat", lambda: wss_agent.poll_ticks())),
            asyncio.create_task(safe_loop("watchdog", lambda: wss_agent.payout_watchdog(logic_engine))),
        )

    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"FATAL: {e}")
    finally:
        try:
            await wss_agent.stop()
        except Exception:
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
            print(f"💀 CRASH #{crash_count}: {e}. Restart in {wait}s...")
            _time.sleep(wait)

if __name__ == "__main__":
    run()
