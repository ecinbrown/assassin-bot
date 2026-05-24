import asyncio
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

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

    def _get_menu_keyboard(self):
        """Persistent keyboard at the bottom of the chat."""
        keyboard = [
            [KeyboardButton("📊 Status"), KeyboardButton("🛑 Pause/Resume")],
            [KeyboardButton("📈 Trades"), KeyboardButton("🔌 Connection")],
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, is_persistent=True)

    async def start_bot(self):
        logger.info("📱 Terminal Velocity Telegram Bot Online!")
        self.app = Application.builder().token(self.bot_token).build()
        
        self.app.add_handler(CommandHandler("start", self.handle_start))
        self.app.add_handler(CallbackQueryHandler(self.button_handler))
        
        # Handle persistent keyboard text buttons
        self.app.add_handler(MessageHandler(filters.Regex("^📊 Status$"), self.handle_status_text))
        self.app.add_handler(MessageHandler(filters.Regex("^🛑 Pause/Resume$"), self.handle_pause_text))
        self.app.add_handler(MessageHandler(filters.Regex("^📈 Trades$"), self.handle_trades_text))
        self.app.add_handler(MessageHandler(filters.Regex("^🔌 Connection$"), self.handle_connection_text))
        
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.message.chat_id
        
        if self.admin_id and chat_id != self.admin_id:
            logger.warning(f"Unauthorized access attempt from {chat_id}")
            return
            
        welcome_msg = (
            "🎯 <b>TERMINAL VELOCITY BOT (POCKETOPTION)</b> 🎯\n\n"
            "I am connected and monitoring OTC markets.\n\n"
            "📊 <b>Strategy:</b> VIP 15M Reversal\n"
            "📡 <b>Mode:</b> Pure WebSocket (no browser)\n"
        )
        
        await update.message.reply_text(
            welcome_msg,
            parse_mode='HTML',
            reply_markup=self._get_menu_keyboard()
        )

    # ─── Persistent keyboard text handlers ───

    async def handle_status_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.admin_id and update.message.chat_id != self.admin_id:
            return
        await self._send_status(update.message)

    async def handle_pause_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.admin_id and update.message.chat_id != self.admin_id:
            return
        self.logic_engine.paused = not self.logic_engine.paused
        state = "PAUSED 🛑" if self.logic_engine.paused else "RUNNING ✅"
        await update.message.reply_text(
            f"🚨 Engine state changed: <b>{state}</b>",
            parse_mode='HTML',
            reply_markup=self._get_menu_keyboard()
        )

    async def handle_trades_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.admin_id and update.message.chat_id != self.admin_id:
            return
        await self._send_trades(update.message)

    async def handle_connection_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if self.admin_id and update.message.chat_id != self.admin_id:
            return
        await self._send_connection_info(update.message)

    # ─── Inline button handler (legacy support) ───

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

    # ─── Status ───

    async def _send_status(self, message):
        try:
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
            
            # Active trade
            trade_info = "None"
            if le.active_trade:
                t = le.active_trade
                trade_info = f"{t['action'].upper()} @ {t['entry']:.5f}"
            
            # Candle data status
            candle_info = "No data yet"
            if le.candle_buffer:
                parts = []
                for s, candles in le.candle_buffer.items():
                    parts.append(f"{s}: {len(candles)} candles")
                candle_info = " | ".join(parts[:3])  # Show max 3
            
            status_msg = (
                "📊 <b>TERMINAL VELOCITY STATUS</b> 📊\n\n"
                f"💰 <b>Balance:</b> <code>{balance_str}</code>\n"
                f"🎯 <b>Active Assets:</b> <code>{sym}</code>\n"
                f"📈 <b>Payout:</b> <code>{payout}%</code>\n"
                f"⚙️ <b>Strategy:</b> <code>VIP 15M Reversal (RSI75 + BB2.5)</code>\n\n"
                f"🏆 <b>Record:</b> <code>{wins}W / {losses}L ({wr_pct})</code>\n"
                f"📌 <b>Active Trade:</b> <code>{trade_info}</code>\n"
                f"📉 <b>Candle Data:</b> <code>{candle_info}</code>\n"
                f"⚡ <b>Engine:</b> <code>{engine_state}</code>\n"
            )
            await message.reply_text(status_msg, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Status command failed: {e}")
            await message.reply_text(f"❌ Status error: <code>{e}</code>", parse_mode='HTML')

    # ─── Connection Info ───

    async def _send_connection_info(self, message):
        try:
            agent = self.browser_agent
            ws_connected = "✅ Connected" if (hasattr(agent, 'ws') and agent.ws and not agent.ws.closed) else "❌ Disconnected"
            authenticated = "✅ Yes" if getattr(agent, '_authenticated', False) else "❌ No"
            subscribed = list(agent.pages.keys()) if agent.pages else ["None"]
            
            msg = (
                "🔌 <b>CONNECTION STATUS</b> 🔌\n\n"
                f"📡 <b>WebSocket:</b> <code>{ws_connected}</code>\n"
                f"🔐 <b>Authenticated:</b> <code>{authenticated}</code>\n"
                f"📺 <b>Subscribed:</b> <code>{', '.join(subscribed)}</code>\n"
                f"💰 <b>Demo Balance:</b> <code>${getattr(agent, 'demo_balance', 0):.2f}</code>\n"
            )
            await message.reply_text(msg, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Connection info failed: {e}")
            await message.reply_text(f"❌ Connection error: <code>{e}</code>", parse_mode='HTML')

    # ─── Trades ───

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

    # ─── Alerts ───

    async def alert_trade_placed(self, symbol, action):
        if not self.admin_id or not self.app: return
        
        stake = 0.0
        trigger = ""
        if self.logic_engine.active_trade:
            stake = self.logic_engine.active_trade.get('stake', 0.0)
            trigger = self.logic_engine.active_trade.get('trigger', '')
        
        msg = (
            f"🔥 <b>TERMINAL VELOCITY TRIGGERED!</b> 🔥\n\n"
            f"<b>Asset:</b> <code>{symbol}</code>\n"
            f"<b>Action:</b> <code>{action.upper()}</code> 🔼🔽\n"
            f"<b>Stake:</b> <code>${float(stake):.2f}</code>\n"
            f"<b>Trigger:</b> <code>{trigger}</code>\n\n"
            f"<i>(Trade sent via WebSocket successfully)</i>"
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
