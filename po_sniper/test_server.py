import asyncio
import os
import logging
from aiohttp import web
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def handle_ping(request):
    return web.Response(text="Terminal Velocity Sniper Online! 🚀")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    app.router.add_get('/health', handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', 8080)
    await site.start()
    logger.info("Web Server listening on port 8080")

async def dummy_telegram():
    token = os.environ.get("TEST_TELEGRAM_TOKEN")
    if not token:
        logger.info("No test token provided, skipping Telegram.")
        return
    
    app = Application.builder().token(token).build()
    
    async def start(update, context):
        await update.message.reply_text("Bot is alive!")
        
    app.add_handler(CommandHandler("start", start))
    
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    logger.info("Telegram polling started")

async def main():
    await start_web_server()
    await dummy_telegram()
    
    # Keep alive
    while True:
        await asyncio.sleep(1)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
