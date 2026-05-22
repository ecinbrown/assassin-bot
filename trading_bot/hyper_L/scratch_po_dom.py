import asyncio
from playwright.async_api import async_playwright
import re

async def scan_po():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        print("Navigating to PocketOption Demo...")
        await page.goto('https://pocketoption.com/en/cabinet/demo-quick-high-low/', wait_until='domcontentloaded')
        
        # Wait 5 seconds for React to render
        await asyncio.sleep(5)
        
        html = await page.content()
        print(f"Captured HTML. Length: {len(html)}")
        
        # Find balance selector
        balance_match = re.search(r'class="([^"]*balance[^"]*)"', html, re.IGNORECASE)
        if balance_match:
            print(f"Possible balance class: {balance_match.group(1)}")
            
        # Find stake amount input
        amount_match = re.search(r'<input[^>]*name="amount"[^>]*>', html, re.IGNORECASE)
        if amount_match:
            print(f"Found amount input: {amount_match.group(0)}")
            
        # Find demo/real switch
        demo_match = re.search(r'<[^>]*class="[^"]*demo[^"]*"[^>]*>', html, re.IGNORECASE)
        if demo_match:
            print(f"Found demo element: {demo_match.group(0)}")

        await browser.close()

if __name__ == '__main__':
    asyncio.run(scan_po())
