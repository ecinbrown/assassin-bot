import asyncio
import os
import sys
import glob
import json
import subprocess
from playwright.async_api import async_playwright, BrowserContext, Page, Playwright
import logging

logger = logging.getLogger(__name__)

class BrowserAgent:
    def __init__(self, tick_queue: asyncio.Queue, auth_state_path: str = None, headless: bool = True):
        self.browser = None
        self.context: BrowserContext = None
        self.primary_page: Page = None
        self._playwright: Playwright = None
        self._user_data_dir = os.path.join(os.getcwd(), 'chrome_profile')
        self.tick_queue = tick_queue
        self.pages = {}
        self.last_known_payout = 92
        self.auth_state_path = auth_state_path
        self.headless = headless
        self.base_stake = 10.0
        self.is_running = False

    def _cleanup_chrome_profile(self):
        """Kill stale Chrome processes and clear lock files."""
        try:
            if sys.platform == 'win32':
                subprocess.run(["taskkill", "/F", "/IM", "chrome.exe"], capture_output=True, timeout=5)
            else:
                subprocess.run(["pkill", "-f", "chromium"], capture_output=True, timeout=5)
        except Exception:
            pass
            
        for pattern in ["SingletonLock", "SingletonCookie", "SingletonSocket", "*lockfile*"]:
            for f in glob.glob(os.path.join(self._user_data_dir, pattern)):
                try: os.remove(f)
                except Exception: pass

    async def start(self):
        self.is_running = True
        logger.info("Initializing Playwright...")
        self._cleanup_chrome_profile()
        self._playwright = await async_playwright().start()
        
        storage_state = self.auth_state_path if self.auth_state_path and os.path.exists(self.auth_state_path) else None
        
        args = [
            "--mute-audio", 
            "--no-sandbox", 
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--js-flags=--max-old-space-size=128",
            "--disable-extensions",
            "--disable-software-rasterizer",
            "--disable-site-isolation-trials"
        ]
        
        self.browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=args
        )
        
        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            storage_state=storage_state
        )
        
        self.primary_page = await self.context.new_page()
        
        # Block media to save memory
        async def block_media(route):
            if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                await route.abort()
            else:
                await route.continue_()
        await self.primary_page.route("**/*", block_media)
        
        await self._inject_price_interceptor()
        
        logger.info("Navigating to PocketOption...")
        try:
            await self.primary_page.goto("https://pocketoption.com/en/cabinet/demo-quick-high-low/", timeout=60000)
            await asyncio.sleep(5)
        except Exception as e:
            logger.warning(f"Navigation error: {e}")

    async def _inject_price_interceptor(self):
        await self.context.add_init_script('''
            window.__po_ticks = [];
            window.__po_raw_events = [];
            const OrigWebSocket = window.WebSocket;
            window.WebSocket = function(...args) {
                const ws = new OrigWebSocket(...args);
                ws.addEventListener('message', function(event) {
                    try {
                        let msg = event.data;
                        if (typeof msg === 'string' && msg.length > 5) {
                            if (msg.startsWith('42["updateHistoryNew"')) {
                                let data = JSON.parse(msg.substring(2))[1];
                                window.__po_ticks.push(data);
                                if (window.__po_ticks.length > 100) window.__po_ticks.shift();
                            }
                        }
                    } catch(e) {}
                });
                return ws;
            };
            window.WebSocket.prototype = OrigWebSocket.prototype;
        ''')

    async def select_top_assets(self, max_assets=5, logic_engine=None):
        logger.info(f"Scanning for top {max_assets} assets with >=92% payout...")
        
        for attempt in range(3):
            try:
                try:
                    await self.primary_page.evaluate('''() => {
                        document.querySelectorAll('.close-button, .modal-close, [data-action="close"], .btn-close').forEach(b => b.click());
                    }''')
                except: pass
                
                asset_button = self.primary_page.locator(".pair-number-wrap, .current-symbol, .asset-info-wrap").first
                await asset_button.click(timeout=15000)
                await asyncio.sleep(3)
                break
            except Exception as e:
                logger.warning(f"Asset selector attempt {attempt+1} failed: {e}")
                try:
                    await self.primary_page.screenshot(path="debug.png")
                    logger.info("Saved debug screenshot to debug.png")
                except: pass
                await asyncio.sleep(5)
                
        top_raw_symbols = []
        try:
            elements = await self.primary_page.evaluate('''() => {
                let results = [];
                document.querySelectorAll("a.alist__link").forEach(el => {
                    let text = el.innerText || "";
                    let match = text.match(/\\+?(\\d+)%/);
                    if (match) {
                        let payout = parseInt(match[1]);
                        if (payout >= 92) {
                            let parts = text.split("\n");
                            if(parts.length > 0) results.push(parts[0].trim());
                        }
                    }
                });
                return results;
            }''')
            
            if elements:
                top_raw_symbols = elements[:max_assets]
                logger.info(f"🎯 Found top assets: {top_raw_symbols}")
            else:
                logger.warning("🚨 No assets found with payout >= 92%!")
                
        except Exception as e:
            logger.error(f"Asset scraping failed: {e}")
            
        finally:
            try:
                await self.primary_page.keyboard.press("Escape")
            except: pass
                
        self.pages = {}
        
        for raw_sym in top_raw_symbols:
            formatted_sym = raw_sym.replace("/", "").replace(" ", "_").replace("OTC", "otc")
            
            if not self.pages:
                page = self.primary_page
            else:
                logger.info(f"Opening new tab for {formatted_sym}...")
                page = await self.context.new_page()
                
                async def block_media(route):
                    if route.request.resource_type in ["image", "media", "font", "stylesheet"]:
                        await route.abort()
                    else:
                        await route.continue_()
                await page.route("**/*", block_media)
                
                try:
                    await page.goto("https://pocketoption.com/en/cabinet/demo-quick-high-low/", timeout=60000)
                    await asyncio.sleep(5)
                except Exception as e:
                    logger.warning(f"Navigation error for {formatted_sym}: {e}")
                    
            try:
                try:
                    await page.evaluate('''() => {
                        document.querySelectorAll('.close-button, .modal-close, [data-action="close"], .btn-close').forEach(b => b.click());
                    }''')
                except: pass
                
                asset_button = page.locator(".pair-number-wrap").first
                await asset_button.click(timeout=8000)
                await asyncio.sleep(2)
                
                target_item = page.locator(f"a.alist__link:has(span:has-text('{raw_sym}'))").first
                await target_item.click(timeout=5000)
                await asyncio.sleep(2)
                
                self.pages[formatted_sym] = page
                logger.info(f"✅ Successfully loaded {formatted_sym} in dedicated page.")
            except Exception as e:
                logger.error(f"Failed to select {formatted_sym} on its page: {e}")
                
        return list(self.pages.keys())

    async def poll_ticks(self):
        while self.is_running:
            await asyncio.sleep(0.5)
            try:
                for symbol, page in list(self.pages.items()):
                    if not page or page.is_closed():
                        continue
                        
                    ticks = await page.evaluate('''() => {
                        let t = window.__po_ticks;
                        window.__po_ticks = [];
                        return t;
                    }''')
                    
                    if ticks:
                        for t in ticks:
                            normalized = {
                                'symbol': symbol,
                                'price': float(t.get('price', t.get('close', t.get('value', 0)))),
                                'timestamp': float(t.get('time', t.get('timestamp', t.get('t', 0)))),
                            }
                            if normalized['price'] > 0:
                                await self.tick_queue.put(normalized)
            except Exception as e:
                if "Target page, context or browser has been closed" in str(e):
                    logger.error("Browser crashed! Attempting recovery...")
                    await self.recover_browser()

    async def change_pair_on_page(self, page, old_symbol, logic_engine):
        try:
            # Open asset menu
            try:
                await page.evaluate('''() => { document.querySelectorAll('.close-button, .modal-close, [data-action="close"], .btn-close').forEach(b => b.click()); }''')
            except: pass
            
            asset_button = page.locator(".pair-number-wrap").first
            await asset_button.click(timeout=8000)
            await asyncio.sleep(2)
            
            # Scrape pairs
            elements = await page.evaluate('''() => {
                let results = [];
                document.querySelectorAll("a.alist__link").forEach(el => {
                    let text = el.innerText || "";
                    let match = text.match(/\\+?(\\d+)%/);
                    if (match) {
                        if (parseInt(match[1]) >= 92) {
                            let parts = text.split("\\n");
                            if(parts.length > 0) results.push(parts[0].trim());
                        }
                    }
                });
                return results;
            }''')
            
            if not elements:
                logger.warning("No assets with >=92% payout found to swap to.")
                await page.keyboard.press("Escape")
                return False
                
            new_sym = None
            for raw_sym in elements:
                formatted_sym = raw_sym.replace("/", "").replace(" ", "_").replace("OTC", "otc")
                if formatted_sym not in self.pages and formatted_sym != old_symbol:
                    new_sym = raw_sym
                    break
                    
            if not new_sym:
                logger.warning("No NEW unused assets with >=92% payout found.")
                await page.keyboard.press("Escape")
                return False
                
            # Click the new asset
            target_item = page.locator(f"a.alist__link:has(span:has-text('{new_sym}'))").first
            await target_item.click(timeout=5000)
            await asyncio.sleep(2)
            
            formatted_new = new_sym.replace("/", "").replace(" ", "_").replace("OTC", "otc")
            del self.pages[old_symbol]
            self.pages[formatted_new] = page
            
            if hasattr(logic_engine, 'target_symbols'):
                if old_symbol in logic_engine.target_symbols:
                    logic_engine.target_symbols.remove(old_symbol)
                if formatted_new not in logic_engine.target_symbols:
                    logic_engine.target_symbols.append(formatted_new)
                    
            logger.info(f"🔄 Swapped dead pair {old_symbol} -> {formatted_new}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to change pair for {old_symbol}: {e}")
            try: await page.keyboard.press("Escape")
            except: pass
            return False

    async def payout_watchdog(self, logic_engine):
        while self.is_running:
            await asyncio.sleep(30)
            try:
                for symbol, page in list(self.pages.items()):
                    if not page or page.is_closed():
                        continue
                        
                    val = await page.evaluate('''() => {
                        let el = document.querySelector(".profit-info .value, .payout-block .value, .profit-value");
                        if (!el) return null;
                        let text = el.innerText || el.textContent;
                        let match = text.match(/(\\d+)/);
                        return match ? parseInt(match[1]) : null;
                    }''')
                    
                    if val:
                        if val < 92:
                            logger.warning(f"⚠️ Payout for {symbol} dropped to {val}%! Swapping pair...")
                            success = await self.change_pair_on_page(page, symbol, logic_engine)
                            if not success:
                                if not hasattr(logic_engine, 'blocked_symbols'):
                                    logic_engine.blocked_symbols = set()
                                logic_engine.blocked_symbols.add(symbol)
                        else:
                            if hasattr(logic_engine, 'blocked_symbols') and symbol in logic_engine.blocked_symbols:
                                logic_engine.blocked_symbols.remove(symbol)
                                logger.info(f"✅ Payout for {symbol} recovered to {val}%. Resuming trades.")
            except Exception:
                pass

    async def execute_trade(self, action: str, amount: float, symbol: str = None):
        if symbol and symbol in self.pages:
            page = self.pages[symbol]
        else:
            page = self.primary_page
            
        if not page or page.is_closed():
            logger.error(f"Cannot trade {symbol}, browser is closed!")
            return 0.0
            
        try:
            # Read current stake from the DOM
            actual_stake = await page.evaluate('''() => {
                let input = document.querySelector(".block--bet-amount input, .amount-value-input, input[name='amount']");
                return input ? parseFloat(input.value) || 0 : 0;
            }''')
            
            if actual_stake <= 0:
                actual_stake = self.base_stake
            
            await asyncio.sleep(0.1)
            
            if action.lower() == 'call':
                btn = page.locator(".btn-call").first
            else:
                btn = page.locator(".btn-put").first
                
            await btn.click(timeout=3000)
            logger.info(f"✅ Injected Playwright Action: {action.upper()} ${actual_stake:.2f} on {symbol}")
            return float(actual_stake)
        except Exception as e:
            logger.error(f"Trade execution failed: {e}")
            return 0.0

    async def recover_browser(self):
        """Auto-recovery if the browser crashes on Render."""
        logger.info("Restarting browser due to crash...")
        try: await self.stop()
        except: pass
        await asyncio.sleep(5)
        await self.start()
        await self.select_top_assets()

    async def stop(self):
        self.is_running = False
        try:
            if self.browser:
                await self.browser.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception as e:
            logger.error(f"Error stopping browser: {e}")
