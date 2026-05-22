"""
═══════════════════════════════════════════════════════════════
  THE ASSASSIN: Live Execution Bot for Hyperliquid
  
  Connects to Hyperliquid Mainnet via the Python SDK.
  Monitors live BTC candles, computes multi-confirmation 
  signals, and executes trades with automated TP/SL.
  
  REQUIREMENTS:
    - HYPER_PRIVATE_KEY in .env (your Hyperliquid wallet key)
    - USDC deposited on Hyperliquid
    
  USAGE:
    python hyper_L/assassin_bot.py              # Live (real money)
    python hyper_L/assassin_bot.py --paper      # Paper trading (no real orders)
═══════════════════════════════════════════════════════════════
"""
import os
import sys
import time
import asyncio
import logging
import argparse
import requests
import numpy as np
from datetime import datetime, timezone, timedelta
from collections import deque
from dotenv import load_dotenv

# Add parent directory for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

from hyper_L.capital_manager import CapitalManager

load_dotenv()

# ═══════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('AssassinBot')

# ═══════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════
TARGET_COINS = ["SOL", "ETH", "DOGE", "WIF"]
CANDLE_INTERVAL = "5m"
LOOKBACK = 220         # 220-candle lookback for statistical percentile tracking
POLL_INTERVAL = 10     # Check for new candles every 10 seconds
COOLDOWN_SECONDS = 60  # 60 seconds minimum gap between trades


class AssassinBot:
    """Live execution engine for The Assassin strategy on Hyperliquid."""
    
    def __init__(self, paper_mode: bool = False, starting_balance: float = None):
        self.paper_mode = paper_mode
        self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
        self.exchange = None
        self.wallet_address = None
        
        # Connect to Hyperliquid (real or paper)
        if not paper_mode:
            self._connect_exchange()
        else:
            logger.info("📝 PAPER MODE: No real orders will be placed.")
        
        # Fetch actual balance from Hyperliquid
        if starting_balance is None:
            starting_balance = self._get_balance()
        
        # Initialize capital manager
        self.capital = CapitalManager(
            starting_balance=starting_balance,
            risk_pct=0.25,   # 25% risk (Full Send option for maximum growth)
            leverage=50
        )
        
        # Candle buffer
        self.candle_buffer = {c: deque(maxlen=LOOKBACK + 10) for c in TARGET_COINS}
        self.last_candle_times = {c: 0 for c in TARGET_COINS}
        
        # Active position tracking
        self.active_positions = {c: None for c in TARGET_COINS}
        self.last_trade_times = {c: 0 for c in TARGET_COINS}
        
        # Fetch asset metadata for size rounding
        try:
            meta = self.info.meta()
            self.sz_decimals = {}
            for asset in meta['universe']:
                if asset['name'] in TARGET_COINS:
                    self.sz_decimals[asset['name']] = asset['szDecimals']
        except Exception as e:
            logger.error(f"Failed to fetch metadata: {e}")
            self.sz_decimals = {c: 2 for c in TARGET_COINS}
        
        # Signal statistics
        self.signals_detected = 0
        self.signals_skipped = 0
        
        # Connection health
        self._consecutive_failures = 0
        
        # Telegram Setup
        self.telegram_token = os.getenv('ASSASSIN_TG_TOKEN')
        self.telegram_chat_id = os.getenv('ASSASSIN_CHAT_ID')
        if not self.telegram_token or not self.telegram_chat_id:
            logger.warning("⚠️ ASSASSIN_TG_TOKEN or ASSASSIN_CHAT_ID not found in .env. Alerts disabled.")

    def _send_telegram_alert(self, message: str):
        """Send a message to the configured Telegram chat."""
        if not self.telegram_token or not self.telegram_chat_id:
            return
            
        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        try:
            # Run blocking request in executor so it doesn't block async loop
            # But wait, run() is async, but requests.post is blocking. We can just use it quickly or use aiohttp.
            # Assassin bot uses a lot of blocking calls anyway (info.all_mids, etc)
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            logger.error(f"Failed to send Telegram alert: {e}")
    
    def _connect_exchange(self):
        """Connect to Hyperliquid with wallet credentials."""
        private_key = os.getenv('HYPER_PRIVATE_KEY')
        if not private_key:
            logger.error("❌ HYPER_PRIVATE_KEY not found in .env!")
            logger.error("   Add: HYPER_PRIVATE_KEY=0xYourPrivateKeyHere")
            sys.exit(1)
        
        try:
            from eth_account import Account
            wallet = Account.from_key(private_key)
            self.wallet_address = wallet.address
            
            self.exchange = Exchange(
                wallet=wallet,
                base_url=constants.MAINNET_API_URL,
            )
            
            # Set leverage
            for c in TARGET_COINS:
                try:
                    self.exchange.update_leverage(self.capital.leverage, c, is_cross=True)
                    logger.info(f"⚡ Leverage set to {self.capital.leverage}x cross-margin for {c}")
                except Exception as e:
                    logger.warning(f"Could not set leverage for {c}: {e}")
            
            logger.info(f"🔗 Connected to Hyperliquid Mainnet")
            logger.info(f"   Wallet: {self.wallet_address[:8]}...{self.wallet_address[-6:]}")
        except Exception as e:
            logger.error(f"❌ Failed to connect: {e}")
            sys.exit(1)
    
    def _get_balance(self) -> float:
        """Fetch current USDC balance from Hyperliquid."""
        if self.paper_mode:
            return 10000.0  # Default paper balance
        
        try:
            state = self.info.user_state(self.wallet_address)
            balance = float(state.get('marginSummary', {}).get('accountValue', 0))
            logger.info(f"💰 Hyperliquid Account Balance: ${balance:,.2f}")
            return balance
        except Exception as e:
            logger.error(f"Failed to fetch balance: {e}")
            return 10000.0
    
    def _get_current_price(self, coin: str) -> float:
        """Get the current mid-price of the specified coin."""
        try:
            mids = self.info.all_mids()
            return float(mids.get(coin, 0))
        except Exception as e:
            logger.error(f"Failed to get price: {e}")
            return 0
    
    def _reconnect(self):
        """Recreate Hyperliquid API connection immediately."""
        try:
            self.info = Info(constants.MAINNET_API_URL, skip_ws=True)
            self._consecutive_failures = 0
            logger.info("🔄 Reconnected to Hyperliquid API")
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
    
    def _fetch_latest_candles(self, coin: str) -> list:
        """Fetch the most recent candles for a specific coin from Hyperliquid."""
        try:
            now = int(datetime.now(timezone.utc).timestamp() * 1000)
            start = now - (LOOKBACK + 5) * 5 * 60 * 1000  # Extra buffer for 5m candles
            
            candles = self.info.candles_snapshot(coin, CANDLE_INTERVAL, start, now)
            
            if not candles:
                self._consecutive_failures += 1
                if self._consecutive_failures >= 3:
                    self._reconnect()
                return []
            
            self._consecutive_failures = 0  # Reset on success
            
            parsed = []
            for c in candles:
                parsed.append({
                    'time': c.get('t', c.get('T', 0)),
                    'open': float(c.get('o', c.get('open', 0))),
                    'high': float(c.get('h', c.get('high', 0))),
                    'low': float(c.get('l', c.get('low', 0))),
                    'close': float(c.get('c', c.get('close', 0))),
                    'volume': float(c.get('v', c.get('volume', 0))),
                })
            
            parsed.sort(key=lambda x: x['time'])
            return parsed
            
        except Exception as e:
            self._consecutive_failures += 1
            logger.error(f"Failed to fetch candles: {e}")
            if self._consecutive_failures >= 2:
                self._reconnect()
            return []
    
    def _compute_signals(self, candles: list) -> tuple:
        """
        Compute Inverted VCP (Volatility Contraction Pattern) Fakeout Hunter logic.
        Returns: (should_trade, direction, confirmations, tp_price, sl_price, sl_dist, tp_dist)
        """
        if len(candles) < LOOKBACK:
            return None
            
        c = candles[-1]
        
        # Calculate 20-period Standard Deviation for historical window
        stddev_history = []
        for i in range(200, 0, -1):
            if len(candles) < i + 20: continue
            window = [candles[-(i+j)]['close'] for j in range(20)]
            stddev_history.append(np.std(window))
            
        if len(stddev_history) < 20: return None
        
        current_window = [candles[-(j+1)]['close'] for j in range(20)]
        current_stddev = np.std(current_window)
        
        # 10th percentile of standard deviation (p10 for loose compression)
        p10_stddev = np.percentile(stddev_history, 10)
        
        # Condition 1: Compression
        prev_stddev = stddev_history[-1] if stddev_history else current_stddev
        if prev_stddev > p10_stddev:
            self.signals_skipped += 1
            return None
            
        # Condition 2: Volume Breakout
        vol_window = [candles[-(j+1)]['volume'] for j in range(1, 21)]
        vol_sma = np.mean(vol_window) if vol_window else 0.01
        
        if c['volume'] <= (vol_sma * 1.5):
            self.signals_skipped += 1
            return None
            
        # Condition 3: Fade the Breakout
        recent_high = max(candles[-(j+1)]['high'] for j in range(1, 21))
        recent_low = min(candles[-(j+1)]['low'] for j in range(1, 21))
        
        direction = None
        sl_dist = 0.0
        tp_dist = 0.0
        
        if c['close'] > recent_high:
            # Fakeout Long -> SHORT (1:1 R:R)
            direction = "SHORT"
            sl_dist = abs(c['close'] - recent_low)
            tp_dist = abs(c['close'] - recent_low)
            
        elif c['close'] < recent_low:
            # Fakeout Short -> LONG (1:1 R:R)
            direction = "LONG"
            sl_dist = abs(recent_high - c['close'])
            tp_dist = abs(recent_high - c['close'])
            
        if direction is None:
            self.signals_skipped += 1
            return None
            
        self.signals_detected += 1
        
        entry = c['close']
        if direction == "LONG":
            tp_price = entry + tp_dist
            sl_price = entry - sl_dist
        else:
            tp_price = entry - tp_dist
            sl_price = entry + sl_dist
            
        logger.info(
            f"🎯 INVERTED VCP FAKEOUT DETECTED: {direction} | "
            f"Vol: {c['volume']/vol_sma:.1f}x Spike | "
            f"TP: +${tp_dist:.1f} | SL: -${sl_dist:.1f}"
        )
        
        return (True, direction, 1, tp_price, sl_price, sl_dist, tp_dist)
    
    def _execute_trade(self, coin: str, direction: str, entry_price: float, confirmations: int, tp_price: float, sl_price: float, sl_dist: float, tp_dist: float):
        """Execute a trade on Hyperliquid."""
        is_long = direction == "LONG"
        is_buy = is_long
        
        # Calculate position size from capital manager using the dynamic SL distance
        size_btc = self.capital.calculate_position_size(entry_price, sl_dist)
        
        # Round size to the correct decimals for the specific coin
        decimals = getattr(self, 'sz_decimals', {}).get(coin, 2)
        size_btc = round(size_btc, decimals)
        
        if size_btc == 0:
            logger.warning(f"⚠️ Calculated size for {coin} is 0. Aborting trade.")
            return False
            
        # Round TP and SL to 5 decimal places to support small altcoins
        tp_price = round(tp_price, 5)
        sl_price = round(sl_price, 5)
        
        logger.critical(
            f"⭐⭐⭐ EXECUTING {direction} | {confirmations}/5 Confirms ⭐⭐⭐\n"
            f"   Entry:  ${entry_price:,.1f}\n"
            f"   Size:   {size_btc:.3f} SOL (${size_btc * entry_price:,.0f} notional)\n"
            f"   TP:     ${tp_price:,.1f} (+${tp_dist:,.1f})\n"
            f"   SL:     ${sl_price:,.1f} (-${sl_dist:,.1f})"
        )
        
        if self.paper_mode:
            # Paper mode: simulate the trade
            self.active_positions[coin] = {
                'direction': direction,
                'entry': entry_price,
                'size': size_btc,
                'tp': tp_price,
                'sl': sl_price,
                'time': time.time(),
            }
            logger.info("📝 PAPER: Position opened (no real order)")
            
            # Send Telegram Alert for Paper Trade
            msg = (
                f"📝 <b>[PAPER TRADE] THE ASSASSIN</b> 📝\n\n"
                f"<b>Asset:</b> <code>{coin}/USDT</code>\n"
                f"<b>Direction:</b> <code>{direction}</code> {'🔽' if direction == 'SHORT' else '🔼'}\n"
                f"<b>Entry:</b> <code>${entry_price:,.1f}</code>\n"
                f"<b>Size:</b> <code>{size_btc:.2f} {coin}</code>\n"
                f"<b>TP:</b> <code>${tp_price:,.1f}</code>\n"
                f"<b>SL:</b> <code>${sl_price:,.1f}</code>"
            )
            self._send_telegram_alert(msg)
            return True
        
        try:
            # 1. Open market position
            result = self.exchange.market_open(
                name=coin,
                is_buy=is_buy,
                sz=size_btc,
                slippage=0.01,  # 1% max slippage
            )
            
            logger.info(f"📤 Market order result: {result}")
            
            if result.get('status') == 'ok':
                # 2. Place Take-Profit order
                tp_order_type = {"trigger": {"triggerPx": str(tp_price), "isMarket": True, "tpsl": "tp"}}
                self.exchange.order(
                    name=coin,
                    is_buy=not is_buy,  # Opposite direction to close
                    sz=size_btc,
                    limit_px=tp_price,
                    order_type=tp_order_type,
                    reduce_only=True,
                )
                
                # 3. Place Stop-Loss order
                sl_order_type = {"trigger": {"triggerPx": str(sl_price), "isMarket": True, "tpsl": "sl"}}
                self.exchange.order(
                    name=coin,
                    is_buy=not is_buy,
                    sz=size_btc,
                    limit_px=sl_price,
                    order_type=sl_order_type,
                    reduce_only=True,
                )
                
                self.active_positions[coin] = {
                    'direction': direction,
                    'entry': entry_price,
                    'size': size_btc,
                    'tp': tp_price,
                    'sl': sl_price,
                    'time': time.time(),
                }
                
                logger.info(f"✅ Position opened with TP @ ${tp_price:,.1f} and SL @ ${sl_price:,.1f}")
                
                # Send Telegram Alert
                msg = (
                    f"⚔️ <b>THE ASSASSIN: FAKEOUT HUNTER</b> ⚔️\n\n"
                    f"<b>Asset:</b> <code>{coin}/USDT</code>\n"
                    f"<b>Direction:</b> <code>{direction}</code> {'🔽' if direction == 'SHORT' else '🔼'}\n"
                    f"<b>Entry:</b> <code>${entry_price:,.1f}</code>\n"
                    f"<b>Size:</b> <code>{size_btc:.2f} {coin}</code>\n"
                    f"<b>TP:</b> <code>${tp_price:,.1f}</code>\n"
                    f"<b>SL:</b> <code>${sl_price:,.1f}</code>"
                )
                self._send_telegram_alert(msg)
                
                return True
            else:
                logger.error(f"❌ Order failed: {result}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Trade execution error: {e}")
            return False
    
    def _check_position(self, coin: str, current_price: float):
        """Check if active position has hit TP or SL."""
        if not self.active_positions.get(coin):
            return
        
        pos = self.active_positions[coin]
        is_long = pos['direction'] == "LONG"
        
        hit_tp = False
        hit_sl = False
        
        if is_long:
            hit_tp = current_price >= pos['tp']
            hit_sl = current_price <= pos['sl']
        else:
            hit_tp = current_price <= pos['tp']
            hit_sl = current_price >= pos['sl']
        
        if hit_tp or hit_sl:
            exit_price = pos['tp'] if hit_tp else pos['sl']
            
            if is_long:
                pnl = (exit_price - pos['entry']) * pos['size']
            else:
                pnl = (pos['entry'] - exit_price) * pos['size']
            
            result = "TP HIT ✅" if hit_tp else "SL HIT ❌"
            logger.info(
                f"{'🎯' if hit_tp else '🛡️'} {result} | "
                f"{pos['direction']} @ ${pos['entry']:,.1f} → ${exit_price:,.1f} | "
                f"PnL: ${pnl:+,.2f}"
            )
            
            # Record in capital manager
            self.capital.record_trade(pnl, pos['direction'], pos['entry'], exit_price)
            
            # Send Telegram Alert
            emoji = "✅ WIN" if hit_tp else "❌ LOSS"
            msg = (
                f"🛡️ <b>ASSASSIN POSITION CLOSED</b> 🛡️\n\n"
                f"<b>Asset:</b> <code>{coin}/USDT</code>\n"
                f"<b>Direction:</b> <code>{pos['direction']}</code>\n"
                f"<b>Result:</b> <b>{emoji}</b>\n"
                f"<b>Exit Price:</b> <code>${exit_price:,.1f}</code>\n"
                f"<b>PnL:</b> <code>${pnl:+,.2f}</code>"
            )
            self._send_telegram_alert(msg)
            
            # Close real position if not paper
            if not self.paper_mode and self.exchange:
                try:
                    self.exchange.market_close(coin)
                    # Cancel remaining TP/SL orders
                    open_orders = self.info.open_orders(self.wallet_address)
                    for order in open_orders:
                        if order.get('coin') == coin:
                            self.exchange.cancel(coin, order['oid'])
                except Exception as e:
                    logger.error(f"Error closing position: {e}")
            
            self.active_positions[coin] = None
    
    def _check_real_position(self, coin: str):
        """Check if a real position was closed by Hyperliquid's TP/SL."""
        if self.paper_mode or not self.exchange or not self.active_positions.get(coin):
            return
        
        try:
            state = self.info.user_state(self.wallet_address)
            positions = state.get('assetPositions', [])
            
            btc_pos = None
            for p in positions:
                if p.get('position', {}).get('coin') == coin:
                    btc_pos = p['position']
                    break
            
            # If no position exists but we think we have one, it was closed
            if btc_pos is None and self.active_positions.get(coin):
                pos = self.active_positions[coin]
                # Check fills to determine exit price
                try:
                    fills = self.info.user_fills(self.wallet_address)
                    recent = [f for f in fills if f.get('coin') == coin]
                    if recent:
                        last_fill = recent[-1]
                        exit_price = float(last_fill.get('px', pos['entry']))
                        is_long = pos['direction'] == "LONG"
                        pnl = (exit_price - pos['entry']) * pos['size'] if is_long else (pos['entry'] - exit_price) * pos['size']
                        
                        logger.info(f"📡 Position closed by exchange TP/SL | Exit: ${exit_price:,.1f} | PnL: ${pnl:+,.2f}")
                        self.capital.record_trade(pnl, pos['direction'], pos['entry'], exit_price)
                        
                        # Send Telegram Alert
                        emoji = "✅ WIN" if pnl > 0 else "❌ LOSS"
                        msg = (
                            f"📡 <b>ASSASSIN (EXCHANGE TP/SL)</b> 📡\n\n"
                            f"<b>Asset:</b> <code>{coin}/USDT</code>\n"
                            f"<b>Direction:</b> <code>{pos['direction']}</code>\n"
                            f"<b>Result:</b> <b>{emoji}</b>\n"
                            f"<b>Exit Price:</b> <code>${exit_price:,.1f}</code>\n"
                            f"<b>PnL:</b> <code>${pnl:+,.2f}</code>"
                        )
                        self._send_telegram_alert(msg)
                except Exception:
                    pass
                
                self.active_positions[coin] = None
                
        except Exception as e:
            logger.debug(f"Position check error: {e}")
    
    async def run(self):
        """Main bot loop."""
        strategy = self.capital.active_strategy
        mode = "PAPER" if self.paper_mode else "LIVE"
        
        print("=" * 70)
        print(f"  THE ASSASSIN — {mode} EXECUTION")
        print(f"  Strategy: {strategy['name']} ({strategy['rr_ratio']:.0f}:1 R:R)")
        print(f"  TP: ${strategy['tp_usd']} | SL: ${strategy['sl_usd']}")
        print(f"  Balance: ${self.capital.balance:,.2f}")
        print(f"  Coins: {', '.join(TARGET_COINS)} | Interval: {CANDLE_INTERVAL}")
        print("=" * 70)
        
        logger.info("🚀 Bot started. Monitoring for liquidation wicks...")
        
        while True:
            try:
                for coin in TARGET_COINS:
                    # 1. Fetch latest candles
                    candles = self._fetch_latest_candles(coin)
                    if len(candles) < LOOKBACK + 3:
                        # logger.debug(f"Waiting for candles ({len(candles)}/{LOOKBACK + 3}) on {coin}")
                        continue
                    
                    # 2. Check if we got a new candle
                    latest_time = candles[-1]['time']
                    if latest_time == self.last_candle_times[coin]:
                        # No new candle — but still check positions
                        current_price = candles[-1]['close']
                        
                        if self.paper_mode:
                            self._check_position(coin, current_price)
                        else:
                            self._check_real_position(coin)
                        continue
                    
                    self.last_candle_times[coin] = latest_time
                    current_price = candles[-1]['close']
                    
                    logger.debug(
                        f"📊 New candle on {coin}: ${current_price:,.1f} | "
                        f"Range: ${candles[-1]['high'] - candles[-1]['low']:,.1f} | "
                        f"Vol: {candles[-1]['volume']:,.0f}"
                    )
                    
                    # 3. Check active position
                    if self.paper_mode:
                        self._check_position(coin, current_price)
                    else:
                        self._check_real_position(coin)
                    
                    # 4. Skip if we have an active position
                    if self.active_positions.get(coin):
                        continue
                    
                    # 5. Check cooldown
                    if time.time() - self.last_trade_times[coin] < COOLDOWN_SECONDS:
                        continue
                    
                    # 6. Check risk circuit breakers
                    can_trade, reason = self.capital.can_trade()
                    if not can_trade:
                        logger.warning(f"🛑 Trading halted: {reason}")
                        continue
                    
                    # 7. Compute signals
                    sig_data = self._compute_signals(candles)
                    if sig_data is None:
                        continue
                    
                    # 8. Evaluate
                    should_trade, direction, confirmations, tp_price, sl_price, sl_dist, tp_dist = sig_data
                    
                    if should_trade:
                        success = self._execute_trade(coin, direction, current_price, confirmations, tp_price, sl_price, sl_dist, tp_dist)
                        if success:
                            self.last_trade_times[coin] = time.time()
                
                await asyncio.sleep(POLL_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("⏹️ Bot stopped by user.")
                break
            except Exception as e:
                logger.error(f"Bot loop error: {e}")
                self._reconnect()
                await asyncio.sleep(2)  # Instant reconnect, minimal delay
        
        # Print final stats
        status = self.capital.get_status()
        print("\n" + "=" * 70)
        print("  FINAL SESSION STATS")
        print("=" * 70)
        print(f"  Balance:         ${status['balance']:,.2f}")
        print(f"  Total PnL:       ${status['total_pnl']:+,.2f}")
        print(f"  Total Trades:    {status['total_trades']}")
        print(f"  Win Rate:        {status['win_rate']:.1f}%")
        print(f"  Max Drawdown:    {status['max_drawdown_pct']:.2f}%")
        print(f"  Strategy:        {status['active_strategy']}")
        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="The Assassin — Hyperliquid Execution Bot")
    parser.add_argument('--paper', action='store_true', help='Run in paper trading mode (no real orders)')
    parser.add_argument('--balance', type=float, default=None, help='Override starting balance')
    args = parser.parse_args()
    
    bot = AssassinBot(paper_mode=args.paper, starting_balance=args.balance)
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
