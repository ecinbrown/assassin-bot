import asyncio
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

logger = logging.getLogger(__name__)

class TerminalTelegramBot:
    def __init__(self, bot_token: str, logic_engine, browser_agent):
        self.bot_token = bot_token
        self.logic_engine = logic_engine
        self.browser_agent = browser_agent
        self.app = None
        
        # Trade history log (last 20 trades)
        self.trade_log = []
        self._MAX_LOG = 20
        
        self.admin_id = os.environ.get("TELEGRAM_CHAT_ID", "5473222741")
        if self.admin_id:
            try:
                self.admin_id = int(self.admin_id)
            except ValueError:
                logger.error("TELEGRAM_CHAT_ID must be a valid integer ID.")
                self.admin_id = None

    async def start_bot(self):
        logger.info("📱 Terminal Velocity Telegram Bot Online!")
        self.app = Application.builder().token(self.bot_token).build()
        
        self.app.add_handler(CommandHandler("start", self.handle_start))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        
        if self.admin_id and chat_id != self.admin_id:
            logger.warning(f"Unauthorized access attempt from {chat_id}")
            return
            
        welcome_msg = (
            "🎯 <b>TERMINAL VELOCITY BOT (POCKETOPTION)</b> 🎯\n\n"
            "I am connected and monitoring OTC markets.\n"
        )
        
        keyboard = [
            [InlineKeyboardButton("📊 Status", callback_data="status"),
             InlineKeyboardButton("🛑 Pause/Resume", callback_data="kill")],
            [InlineKeyboardButton("📈 Trades", callback_data="trades")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(welcome_msg, parse_mode='HTML', reply_markup=reply_markup)

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        chat_id = query.message.chat_id
        
        if self.admin_id and chat_id != self.admin_id:
            await query.answer("Unauthorized", show_alert=True)
            return
            
        await query.answer()
        
        if query.data == "status":
            await self._send_status(query.message)
        elif query.data == "kill":
            self.logic_engine.paused = not self.logic_engine.paused
            state = "PAUSED 🛑" if self.logic_engine.paused else "RUNNING ✅"
            await query.message.reply_text(f"🚨 Engine state changed: <b>{state}</b>", parse_mode='HTML')
        elif query.data == "trades":
            await self._send_trades(query.message)

    async def _send_status(self, message):
        payout = getattr(self.browser_agent, 'last_known_payout', 92)
        sym = ", ".join(self.browser_agent.pages.keys()) if self.browser_agent.pages else 'None'
        
        # Get balance from WSS agent
        if hasattr(self.browser_agent, 'demo_balance'):
            balance_str = f"${self.browser_agent.demo_balance:.2f}"
        else:
            balance_str = "UNKNOWN"
        
        # Engine stats
        le = self.logic_engine
        wins = le.wins
        losses = le.losses
        total = wins + losses
        wr_pct = f"{wins/total*100:.0f}%" if total > 0 else "N/A"
        engine_state = "PAUSED 🛑" if le.paused else "RUNNING ✅"
        
        # RTO state
        rto_info = "No active tracking"
        if le.rto_blocks:
            for sym_key, r in le.rto_blocks.items():
                armed = "🔫 ARMED" if r.get('is_armed') else "⏳ Watching"
                rto_info = f"{sym_key}: {armed} | Crossings: {r.get('crossings', 0)} | Dir: {r.get('direction', '-')}"
                break  # Show first symbol only
        
        # Active trade
        trade_info = "None"
        if le.active_trade:
            t = le.active_trade
            trade_info = f"{t['action'].upper()} @ {t['entry']:.5f}"
        
        status_msg = (
            "📊 <b>TERMINAL VELOCITY STATUS</b> 📊\n\n"
            f"💰 <b>Live Balance:</b> <code>{balance_str}</code>\n"
            f"🎯 <b>Active Asset:</b> <code>{sym}</code>\n"
            f"📈 <b>Current Payout:</b> <code>{payout}%</code>\n"
            f"⚙️ <b>Risk Strategy:</b> <code>Kelly Optimal</code>\n\n"
            f"🏆 <b>Record:</b> <code>{wins}W / {losses}L ({wr_pct})</code>\n"
            f"🔫 <b>RTO Engine:</b> <code>{rto_info}</code>\n"
            f"📌 <b>Active Trade:</b> <code>{trade_info}</code>\n"
            f"⚡ <b>Engine:</b> <code>{engine_state}</code>\n"
        )
        await message.reply_text(status_msg, parse_mode='HTML')

    async def _send_trades(self, message):
        """Send the last 20 trade results."""
        if not self.trade_log:
            await message.reply_text("📈 <b>No trades recorded yet.</b>", parse_mode='HTML')
            return
        
        lines = ["📈 <b>RECENT TRADES</b> 📈\n"]
        for i, t in enumerate(reversed(self.trade_log), 1):
            emoji = "✅" if t['win'] else "❌"
            lines.append(f"{emoji} <code>{t['symbol']} {t['action'].upper()} | {t['trigger']}</code>")
        
        await message.reply_text("\n".join(lines), parse_mode='HTML')

    async def alert_trade_placed(self, symbol, action):
        if not self.admin_id or not self.app: return
        
        stake = 0.0
        if self.logic_engine.active_trade:
            stake = self.logic_engine.active_trade.get('stake', 0.0)
        
        trigger = ""
        if self.logic_engine.active_trade:
            trigger = self.logic_engine.active_trade.get('trigger', '')
        
        msg = (
            f"🔥 <b>TERMINAL VELOCITY TRIGGERED!</b> 🔥\n\n"
            f"<b>Asset:</b> <code>{symbol}</code>\n"
            f"<b>Action:</b> <code>{action.upper()}</code> 🔼🔽\n"
            f"<b>Stake:</b> <code>${float(stake):.2f}</code>\n"
            f"<b>Trigger:</b> <code>{trigger}</code>\n\n"
            f"<i>(Trade sent to PocketOption successfully)</i>"
        )
        try:
            await self.app.bot.send_message(chat_id=self.admin_id, text=msg, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to send trade alert: {e}")

    async def alert_trade_result(self, symbol, action, win, is_martingale=False):
        if not self.admin_id or not self.app: return
        
        # Log the trade
        trigger = ""
        if self.logic_engine.active_trade:
            trigger = self.logic_engine.active_trade.get('trigger', '')
        self.trade_log.append({
            'symbol': symbol,
            'action': action,
            'win': win,
            'trigger': trigger
        })
        if len(self.trade_log) > self._MAX_LOG:
            self.trade_log.pop(0)
        
        emoji = "✅ WIN" if win else "❌ LOSS"
        le = self.logic_engine
        total = le.wins + le.losses
        wr_pct = f"{le.wins/total*100:.0f}%" if total > 0 else "N/A"
        
        msg = (
            f"Trade Result for {symbol} ({action.upper()}): <b>{emoji}</b>\n"
            f"📊 Record: <code>{le.wins}W / {le.losses}L ({wr_pct})</code>"
        )
        try:
            await self.app.bot.send_message(chat_id=self.admin_id, text=msg, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to send result alert: {e}")
