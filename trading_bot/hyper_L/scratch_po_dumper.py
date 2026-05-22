import asyncio
from playwright.async_api import async_playwright
import time

async def manual_scan():
    async with async_playwright() as p:
        # Launching with user profile to bypass the login splash screen if possible
        # Or at least setting viewport large enough so the app renders
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(viewport={'width': 1280, 'height': 800})
        page = await context.new_page()
        
        print("Navigating to PocketOption...")
        await page.goto('https://pocketoption.com/en/cabinet/demo-quick-high-low/', timeout=60000)
        
        print("Waiting 15 seconds for manual DOM render (Watch the screen)...")
        await asyncio.sleep(15)
        
        html = await page.content()
        with open("po_dom_dump.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("Dumped full DOM to po_dom_dump.html")
        
        await browser.close()

if __name__ == '__main__':
    asyncio.run(manual_scan())
