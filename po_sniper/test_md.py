import asyncio
import os
from telegram.ext import Application, CommandHandler

async def test():
    token = os.environ.get("TELEGRAM_TEST_TOKEN")
    if not token:
        print("Need token to test")
        return
    app = Application.builder().token(token).build()
    
    async def start(update, context):
        try:
            welcome_msg = (
                "🎯 *TERMINAL VELOCITY BOT (POCKETOPTION)* 🎯\n\n"
                "I am connected and monitoring OTC markets for the 72.7% edge.\n"
                "Use the commands below to interact:\n"
                "/po_status - Check balance and active asset\n"
                "/kill - Pause or unpause the engine"
            )
            await update.message.reply_text(welcome_msg, parse_mode='Markdown')
            print("SUCCESS")
        except Exception as e:
            print("FAILED:", e)
            
    app.add_handler(CommandHandler("start", start))
    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("Running...")
    await asyncio.sleep(5)
    await app.updater.stop()
    await app.stop()
    await app.shutdown()

if __name__ == "__main__":
    pass
