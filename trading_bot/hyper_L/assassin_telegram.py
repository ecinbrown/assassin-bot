"""
═══════════════════════════════════════════════════════════════
  THE ASSASSIN — Telegram Command Center
  
  Control the Assassin bot entirely from Telegram:
  /start  - Interactive menu
  /status - Bot status & balance
  /kill   - Stop the bot
  /trades - Recent trade history
  
  USAGE:
    python hyper_L/assassin_telegram.py              # Live
    python hyper_L/assassin_telegram.py --paper       # Paper mode
═══════════════════════════════════════════════════════════════
"""
import os
import sys
import asyncio
import logging
import argparse
import signal
from datetime import datetime, timezone
from dotenv import load_dotenv
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
load_dotenv()

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes
)

from hyper_L.assassin_bot import AssassinBot, TARGET_COINS
from hyper_L.capital_manager import CapitalManager

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('AssassinTG')

# ═══════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════
TG_TOKEN = os.getenv("ASSASSIN_TG_TOKEN", "7906303240:AAGp3GA2dobQ1-5AUtZu0tkFI0I9RSFKKy8")
# Updated List for You and Your Friends
AUTHORIZED_IDS = [5473222741, 6363315804, 6891630125]


class AssassinController:
    """Manages the Assassin bot lifecycle via Telegram."""

    def __init__(self, paper_mode: bool = False, balance: float = None):
        self.paper_mode = paper_mode
        self.balance = balance
        self.bot_instance: AssassinBot = None
        self.bot_task: asyncio.Task = None
        self.running = False
        self.tg_app: Application = None
        self.start_time = None

    async def send(self, text: str):
        """Send a message to ALL authorized users."""
        for user_id in AUTHORIZED_IDS:
            try:
                await self.tg_app.bot.send_message(
                    chat_id=user_id, text=text, parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"TG send error for {user_id}: {e}")

    def _main_menu(self):
        mode = "🟢 LIVE" if not self.paper_mode else "📝 PAPER"
        status = "🟢 Running" if self.running else "🔴 Stopped"
        mode_btn = "Switch to 🟢 LIVE" if self.paper_mode else "Switch to 📝 PAPER"
        kb = [
            [InlineKeyboardButton(f"{'🛑 Stop Bot' if self.running else '🚀 Start Bot'}", callback_data="toggle")],
            [InlineKeyboardButton("📊 Status", callback_data="status"),
             InlineKeyboardButton("📜 Trades", callback_data="trades")],
            [InlineKeyboardButton("💰 Balance", callback_data="balance"),
             InlineKeyboardButton("🔄 Signals", callback_data="signals")],
            [InlineKeyboardButton(mode_btn, callback_data="mode_toggle")],
        ]
        text = (
            f"<b>⚔️ THE ASSASSIN</b>\n\n"
            f"Mode: {mode}\n"
            f"Bot: {status}\n\n"
            f"Select an option:"
        )
        return text, InlineKeyboardMarkup(kb)

    async def cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in AUTHORIZED_IDS:
            return
        text, kb = self._main_menu()
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

    async def cmd_status(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in AUTHORIZED_IDS:
            return
        await update.message.reply_text(self._get_status_text(), parse_mode="HTML")

    async def cmd_kill(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in AUTHORIZED_IDS:
            return
        await self._stop_bot()
        await update.message.reply_text("🛑 Bot stopped.", parse_mode="HTML")

    async def cmd_trades(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in AUTHORIZED_IDS:
            return
        await update.message.reply_text(self._get_trades_text(), parse_mode="HTML")

    async def button_handler(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if query.from_user.id not in AUTHORIZED_IDS:
            return
        await query.answer()

        if query.data == "toggle":
            if self.running:
                await self._stop_bot()
            else:
                await self._start_bot()
            text, kb = self._main_menu()
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

        elif query.data == "status":
            await query.edit_message_text(self._get_status_text(), parse_mode="HTML")

        elif query.data == "trades":
            await query.edit_message_text(self._get_trades_text(), parse_mode="HTML")

        elif query.data == "balance":
            await query.edit_message_text(self._get_balance_text(), parse_mode="HTML")

        elif query.data == "signals":
            await query.edit_message_text(self._get_signals_text(), parse_mode="HTML")

        elif query.data == "menu":
            text, kb = self._main_menu()
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

        elif query.data == "mode_toggle":
            if self.running:
                await self._stop_bot()
            self.paper_mode = not self.paper_mode
            new_mode = "📝 PAPER" if self.paper_mode else "🟢 LIVE"
            await self.send(f"🔀 Switched to <b>{new_mode}</b> mode")
            await self._start_bot()
            text, kb = self._main_menu()
            await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

    def _get_status_text(self) -> str:
        if not self.bot_instance or not self.running:
            return "🔴 <b>Bot is not running.</b>\n\nUse /start to launch."

        s = self.bot_instance.capital.get_status()
        uptime = ""
        if self.start_time:
            delta = datetime.now(timezone.utc) - self.start_time
            hours = int(delta.total_seconds() // 3600)
            mins = int((delta.total_seconds() % 3600) // 60)
            uptime = f"{hours}h {mins}m"

        mode = "📝 PAPER" if self.paper_mode else "🟢 LIVE"
        pos = "None"
        if self.bot_instance.active_positions:
            active = []
            for coin, p in self.bot_instance.active_positions.items():
                if p:
                    active.append(f"{coin}: {p['direction']} @ ${p['entry']:,.0f}")
            if active:
                pos = "\n  ".join(active)

        return (
            f"<b>⚔️ ASSASSIN STATUS</b>\n\n"
            f"Mode: {mode}\n"
            f"Uptime: {uptime}\n"
            f"Balance: <b>${s['balance']:,.2f}</b>\n"
            f"Total PnL: <b>${s['total_pnl']:+,.2f}</b>\n"
            f"Trades: {s['total_trades']} ({s['wins']}W / {s['losses']}L)\n"
            f"Win Rate: {s['win_rate']:.1f}%\n"
            f"Drawdown: {s['max_drawdown_pct']:.2f}%\n"
            f"Active: {pos}\n"
            f"Strategy: {s['active_strategy']}"
        )

    def _get_trades_text(self) -> str:
        if not self.bot_instance:
            return "🔴 Bot not initialized."

        history = self.bot_instance.capital.trade_history[-10:]
        if not history:
            return "📜 <b>No trades yet.</b>"

        lines = ["<b>📜 RECENT TRADES</b>\n"]
        for t in reversed(history):
            icon = "✅" if t['pnl'] > 0 else "❌"
            lines.append(
                f"{icon} {t['direction']} | ${t['entry']:,.0f}→${t['exit']:,.0f} | "
                f"<b>${t['pnl']:+,.2f}</b>"
            )
        return "\n".join(lines)

    def _get_balance_text(self) -> str:
        if not self.bot_instance:
            return "🔴 Bot not initialized."
        s = self.bot_instance.capital.get_status()
        return (
            f"<b>💰 BALANCE</b>\n\n"
            f"Current: <b>${s['balance']:,.2f}</b>\n"
            f"Initial: ${self.bot_instance.capital.initial_balance:,.2f}\n"
            f"PnL: <b>${s['total_pnl']:+,.2f}</b>\n"
            f"Peak: ${self.bot_instance.capital.peak_balance:,.2f}\n"
            f"Risk: {self.bot_instance.capital.risk_pct*100:.1f}% per trade"
        )

    def _get_signals_text(self) -> str:
        if not self.bot_instance:
            return "🔴 Bot not initialized."
        try:
            signals_output = []
            for coin in TARGET_COINS:
                candles = self.bot_instance._fetch_latest_candles(coin)
                if not candles or len(candles) < 220:
                    signals_output.append(f"<b>{coin}:</b> ⚠️ Wait ({len(candles) if candles else 0}/220)")
                    continue
                    
                c = candles[-1]
                
                # Calculate metrics
                stddev_history = []
                for i in range(200, 0, -1):
                    window = [candles[-(i+j)]['close'] for j in range(20)]
                    stddev_history.append(np.std(window))
                    
                current_window = [candles[-(j+1)]['close'] for j in range(20)]
                current_stddev = np.std(current_window)
                p10_stddev = np.percentile(stddev_history, 10)
                
                vol_window = [candles[-(j+1)]['volume'] for j in range(1, 21)]
                vol_sma = np.mean(vol_window) if vol_window else 0.01
                vol_spike = c['volume'] / vol_sma
                
                is_compressed = current_stddev <= p10_stddev
                is_vol_spike = vol_spike >= 1.5
                
                recent_high = max(candles[-(j+1)]['high'] for j in range(1, 21))
                recent_low = min(candles[-(j+1)]['low'] for j in range(1, 21))

                comp_status = '✅' if is_compressed else '❌'
                vol_status = '✅' if is_vol_spike else '❌'
                
                signals_output.append(
                    f"<b>{coin}:</b> ${c['close']:,.2f}\n"
                    f"  Comp: {comp_status} | Vol: {vol_status} ({vol_spike:.1f}x)"
                )
            
            return "<b>🔄 VCP HUNTER SIGNALS</b>\n\n" + "\n\n".join(signals_output)
        except Exception as e:
            return f"⚠️ Signal check error: {e}"

    async def _start_bot(self):
        if self.running:
            return

        self.bot_instance = AssassinBot(
            paper_mode=self.paper_mode,
            starting_balance=self.balance
        )
        
        # ── Patch 1: Signal detection notifications ──
        original_compute = self.bot_instance._compute_signals
        controller = self

        def patched_compute(candles):
            result = original_compute(candles)
            if result is not None:
                should_trade, direction, confirmations, tp_price, sl_price, sl_dist, tp_dist = result
                entry = candles[-1]['close']
                emoji = "🔼" if direction == "LONG" else "🔽"
                msg = (
                    f"🎯 <b>SIGNAL DETECTED</b> {emoji}\n\n"
                    f"Direction: <code>{direction}</code>\n"
                    f"Entry: <code>${entry:,.4f}</code>\n"
                    f"TP: <code>${tp_price:,.4f}</code>\n"
                    f"SL: <code>${sl_price:,.4f}</code>\n"
                    f"R:R: 1:1"
                )
                try:
                    asyncio.create_task(controller.send(msg))
                except Exception:
                    pass
            return result
        
        self.bot_instance._compute_signals = patched_compute

        # ── Patch 2: Trade execution notifications ──
        original_execute = self.bot_instance._execute_trade
        
        def patched_execute(coin, direction, entry_price, confirmations, tp_price, sl_price, sl_dist, tp_dist):
            success = original_execute(coin, direction, entry_price, confirmations, tp_price, sl_price, sl_dist, tp_dist)
            if success:
                emoji = "🔼" if direction == "LONG" else "🔽"
                mode = "📝 PAPER" if controller.bot_instance.paper_mode else "🟢 LIVE"
                msg = (
                    f"⚔️ <b>TRADE OPENED</b> {emoji}\n\n"
                    f"Mode: {mode}\n"
                    f"Asset: <code>{coin}/USDT</code>\n"
                    f"Direction: <code>{direction}</code>\n"
                    f"Entry: <code>${entry_price:,.4f}</code>\n"
                    f"TP: <code>${tp_price:,.4f}</code>\n"
                    f"SL: <code>${sl_price:,.4f}</code>"
                )
                try:
                    asyncio.create_task(controller.send(msg))
                except Exception:
                    pass
            return success
        
        self.bot_instance._execute_trade = patched_execute

        # ── Patch 3: Trade close notifications ──
        original_record = self.bot_instance.capital.record_trade

        def patched_record(pnl, direction, entry, exit_price):
            original_record(pnl, direction, entry, exit_price)
            icon = "✅ WIN" if pnl > 0 else "❌ LOSS"
            s = controller.bot_instance.capital.get_status()
            msg = (
                f"<b>{icon}</b>\n\n"
                f"Direction: {direction}\n"
                f"Entry: ${entry:,.4f}\n"
                f"Exit: ${exit_price:,.4f}\n"
                f"PnL: <b>${pnl:+,.2f}</b>\n\n"
                f"Balance: <b>${s['balance']:,.2f}</b>\n"
                f"Record: {s['wins']}W / {s['losses']}L ({s['win_rate']:.0f}%)"
            )
            asyncio.create_task(controller.send(msg))

        self.bot_instance.capital.record_trade = patched_record

        self.running = True
        self.start_time = datetime.now(timezone.utc)
        self.bot_task = asyncio.create_task(self._run_bot_loop())

        mode = "PAPER" if self.paper_mode else "LIVE"
        coins_str = ", ".join(TARGET_COINS)
        await self.send(
            f"🚀 <b>Assassin Started ({mode})</b>\n"
            f"Balance: ${self.bot_instance.capital.balance:,.2f}\n"
            f"Strategy: {self.bot_instance.capital.active_strategy['name']}\n"
            f"Monitoring: {coins_str}"
        )

    async def _run_bot_loop(self):
        crash_count = 0
        while self.running:
            try:
                await self.bot_instance.run()
            except asyncio.CancelledError:
                logger.info("Bot task cancelled")
                return
            except Exception as e:
                crash_count += 1
                wait = min(5 * crash_count, 30)
                logger.error(f"Bot crashed (#{crash_count}): {e}")
                await self.send(
                    f"⚠️ <b>Bot crashed (#{crash_count}):</b> {e}\n"
                    f"Auto-restarting in {wait}s..."
                )
                await asyncio.sleep(wait)
                if self.running:
                    try:
                        self.bot_instance = AssassinBot(
                            paper_mode=self.paper_mode,
                            starting_balance=self.balance
                        )
                        crash_count = 0
                        await self.send("🔄 <b>Bot restarted successfully</b>")
                    except Exception as e2:
                        logger.error(f"Failed to recreate bot: {e2}")
                        await self.send(f"❌ Restart failed: {e2}")

    async def _stop_bot(self):
        self.running = False
        if self.bot_task:
            self.bot_task.cancel()
            try:
                await self.bot_task
            except (asyncio.CancelledError, Exception):
                pass
            self.bot_task = None
        await self.send("🛑 <b>Assassin Stopped</b>")

    async def cmd_menu(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in AUTHORIZED_IDS:
            return
        text, kb = self._main_menu()
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

    async def cmd_signals(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id not in AUTHORIZED_IDS:
            return
        await update.message.reply_text(self._get_signals_text(), parse_mode="HTML")

    async def run_telegram(self):
        self.tg_app = Application.builder().token(TG_TOKEN).build()

        # Register command handlers
        self.tg_app.add_handler(CommandHandler("start", self.cmd_start))
        self.tg_app.add_handler(CommandHandler("menu", self.cmd_menu))
        self.tg_app.add_handler(CommandHandler("status", self.cmd_status))
        self.tg_app.add_handler(CommandHandler("kill", self.cmd_kill))
        self.tg_app.add_handler(CommandHandler("trades", self.cmd_trades))
        self.tg_app.add_handler(CommandHandler("signals", self.cmd_signals))
        self.tg_app.add_handler(CallbackQueryHandler(self.button_handler))

        await self.tg_app.initialize()
        await self.tg_app.start()

        await self.tg_app.bot.set_my_commands([
            BotCommand("start", "🚀 Launch Assassin"),
            BotCommand("menu", "⚔️ Main Menu"),
            BotCommand("status", "📊 Bot Status & Balance"),
            BotCommand("trades", "📜 Recent Trades"),
            BotCommand("signals", "🔄 Live SOL Signals"),
            BotCommand("kill", "🛑 Stop The Bot"),
        ])
        
        await self.tg_app.updater.start_polling()
        await self.send("⚔️ <b>Assassin Command Center Online</b>\n\nTap ☰ for menu or send /start")

        await self._start_bot()
        await self._start_health_server()
        asyncio.create_task(self._watchdog())
        asyncio.create_task(self._heartbeat())

        stop_event = asyncio.Event()
        await stop_event.wait()

    async def _heartbeat(self):
        """Send a heartbeat every hour so you know the bot is alive."""
        while True:
            await asyncio.sleep(3600)  # 1 hour
            if self.running and self.bot_instance:
                s = self.bot_instance.capital.get_status()
                uptime = ""
                if self.start_time:
                    delta = datetime.now(timezone.utc) - self.start_time
                    hours = int(delta.total_seconds() // 3600)
                    mins = int((delta.total_seconds() % 3600) // 60)
                    uptime = f"{hours}h {mins}m"
                await self.send(
                    f"💓 <b>Heartbeat</b>\n\n"
                    f"Uptime: {uptime}\n"
                    f"Balance: ${s['balance']:,.2f}\n"
                    f"Trades: {s['total_trades']} ({s['wins']}W / {s['losses']}L)\n"
                    f"Signals scanned: {self.bot_instance.signals_detected} detected, "
                    f"{self.bot_instance.signals_skipped} skipped"
                )

    async def _watchdog(self):
        while True:
            await asyncio.sleep(30)
            if self.running and (self.bot_task is None or self.bot_task.done()):
                await self.send("🐕 <b>Watchdog detected crash. Restarting...</b>")
                try:
                    await self._start_bot()
                except Exception as e:
                    logger.error(f"Watchdog restart failed: {e}")

    async def _start_health_server(self):
        from aiohttp import web
        
        async def health(request):
            status = "running" if self.running else "stopped"
            bal = "N/A"
            if self.bot_instance:
                try:
                    bal = f"${self.bot_instance.capital.balance:,.2f}"
                except: pass
            return web.Response(text=f"Assassin: {status} | Balance: {bal}")
            
        async def telemetry(request):
            if not self.bot_instance:
                return web.json_response({"error": "Bot not initialized"}, status=503)
            try:
                state = self.bot_instance.capital.get_status()
                return web.json_response({
                    "status": "running" if self.running else "stopped",
                    "paper_mode": self.paper_mode,
                    "balance": state["balance"],
                    "peak_balance": state["peak_balance"],
                    "total_pnl": state["total_pnl"],
                    "total_trades": state["total_trades"],
                    "win_rate": state["win_rate"],
                    "max_drawdown_pct": state["max_drawdown_pct"],
                    "active_positions": self.bot_instance.active_positions,
                    "trade_history": self.bot_instance.capital.trade_history[-10:] if self.bot_instance.capital.trade_history else [],
                    "timestamp": __import__('time').time()
                })
            except Exception as e:
                return web.json_response({"error": str(e)}, status=500)
        
        app = web.Application()
        app.router.add_get("/", health)
        app.router.add_get("/health", health)
        app.router.add_get("/telemetry", telemetry)
        
        runner = web.AppRunner(app)
        await runner.setup()
        port = int(os.getenv("PORT", "8080"))
        site = web.TCPSite(runner, "0.0.0.0", port)
        await site.start()
        logger.info(f"🌐 Health server on port {port}")


def main():
    parser = argparse.ArgumentParser(description="Assassin Telegram Controller")
    parser.add_argument('--paper', action='store_true', help='Paper trading mode')
    parser.add_argument('--balance', type=float, default=None, help='Starting balance')
    args = parser.parse_args()

    while True:
        try:
            controller = AssassinController(paper_mode=args.paper, balance=args.balance)
            asyncio.run(controller.run_telegram())
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Fatal crash in Telegram Controller: {e}")
            import time
            time.sleep(10)
            continue


if __name__ == "__main__":
    main()
