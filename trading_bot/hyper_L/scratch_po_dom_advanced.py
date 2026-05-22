import asyncio
from playwright.async_api import async_playwright

async def get_selectors():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto('https://pocketoption.com/en/cabinet/demo-quick-high-low/', wait_until='networkidle')
        
        # We inject a script to extract all classes containing "balance", "amount", or "demo"
        data = await page.evaluate('''() => {
            let res = { balances: [], amounts: [], demo_buttons: [], calls: [], puts: [] };
            
            // Look for things that look like a balance
            document.querySelectorAll('[class*="balance"]').forEach(el => {
                res.balances.push({tag: el.tagName, className: el.className, text: el.innerText});
            });
            
            // Look for things that look like an amount input
            document.querySelectorAll('input[type="text"], input[type="number"]').forEach(el => {
                if(el.className.includes('amount') || el.name.includes('amount')) {
                    res.amounts.push({className: el.className, name: el.name});
                }
            });
            
            // Look for account type toggle
            document.querySelectorAll('[class*="demo"], [class*="real"]').forEach(el => {
                if(el.tagName === 'A' || el.tagName === 'BUTTON' || el.tagName === 'DIV') {
                   res.demo_buttons.push({tag: el.tagName, className: el.className, text: el.innerText});
                }
            });
            
            // Look for call/put buttons
            document.querySelectorAll('.btn-call, .btn-put, [class*="btn-call"], [class*="btn-put"]').forEach(el => {
                res.calls.push({className: el.className});
            });
            
            return res;
        }''')
        
        print("--- EXTRACTED DOM SELECTORS ---")
        for k, v in data.items():
            print(f"\\n{k.upper()}:")
            for item in v[:5]:  # limit to first 5
                print(item)
                
        await browser.close()

if __name__ == '__main__':
    asyncio.run(get_selectors())
