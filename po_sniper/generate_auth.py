import asyncio
from playwright.async_api import async_playwright

async def capture_auth():
    print("==================================================")
    print("🔑 POCKETOPTION SESSION AUTHENTICATOR")
    print("==================================================")
    print("1. A browser window will open.")
    print("2. Log into your PocketOption account.")
    print("3. Solve any Captchas.")
    print("4. Make sure you are on the Trading Screen.")
    print("5. Switch to Demo or Real account (whichever you want to use).")
    print("6. COME BACK TO THIS CONSOLE AND PRESS ENTER.")
    print("==================================================\n")
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()
        
        await page.goto('https://pocketoption.com/en/login/')
        
        input("\n🚨 PRESS ENTER HERE ONLY AFTER YOU HAVE LOGGED IN AND THE TRADING CHART IS LOADED 🚨\n")
        
        await context.storage_state(path="auth_state.json")
        
        print("✅ SUCCESS: Session cookies saved to 'auth_state.json'!")
        print("This file will be used by the headless bot on Render to bypass the login screen.")
        
        await browser.close()

if __name__ == "__main__":
    asyncio.run(capture_auth())
