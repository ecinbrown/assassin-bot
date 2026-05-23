import asyncio
from telegram.ext import Application

async def test():
    print("Building app")
    app = Application.builder().token('7771345334:AAG4o1afylJuHWqT2YUnm2oFfcdfURnlbUE').build()
    print("Init")
    await app.initialize()
    print("Start")
    await app.start()
    print("Polling")
    await app.updater.start_polling()
    print('SUCCESS NOT BLOCKED')
    await app.updater.stop()
    await app.stop()
    await app.shutdown()

asyncio.run(test())
