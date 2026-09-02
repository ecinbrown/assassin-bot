"""
Assassin Bot - Telegram Controller & Live Alert Engine
======================================================
Provides interactive Telegram control for Assassin Bot:
- Real-time trade and signal alerts with full price-action breakdown.
- Dynamic mode switching between DEMO (Simulation) and REAL (Live Web3).
- Stake adjustment, symbol management, status dashboard, and auto-claim triggers.
"""
import asyncio
import logging
import os
import time
from typing import Optional, List, Dict
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

logger = logging.getLogger("AssassinTelegram")


AUTHORIZED_CHAT_IDS = [6363315804]


class AssassinTelegramBot:
    """Interactive Telegram interface for Assassin Bot."""

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None, main_controller=None):
        self.token = token or os.environ.get("ASSASSIN_TG_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN", "8295109367:AAHeUa5k_eIpl-OQb9LcuOUekBiGL7D8FQQ")
        chat_id_val = chat_id or os.environ.get("ASSASSIN_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID") or "6363315804"
        self.chat_id = int(chat_id_val) if str(chat_id_val).lstrip('-').isdigit() else 6363315804
        
        self.chat_ids = set(AUTHORIZED_CHAT_IDS)
        self.chat_ids.add(6363315804)
        if self.chat_id:
            self.chat_ids.add(self.chat_id)

        self.controller = main_controller  # Reference to main context (engine, prdt_agent, feed)
        self.app: Optional[Application] = None
        self.is_running = False

    def _get_keyboard(self) -> ReplyKeyboardMarkup:
        """Create persistent quick-action keyboard."""
        keyboard = [
            [KeyboardButton("📊 Status"), KeyboardButton("🎁 Claim Winnings")],
            [KeyboardButton("🧪 Switch to DEMO"), KeyboardButton("🟢 Switch to REAL")],
            [KeyboardButton("🛑 Pause / Resume")]
        ]
        return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

    async def _check_auth(self, update: Update) -> bool:
        """Authorize message sender against configured chat_id."""
        if not update or not update.effective_chat:
            return False
        user_id = update.effective_chat.id
        self.chat_ids.add(user_id)
        self.chat_id = user_id
        return True

    def initialize(self):
        """Build Telegram Application and register command handlers."""
        if not self.token:
            logger.warning("⚠️ No ASSASSIN_TG_TOKEN configured. Telegram bot disabled.")
            return False

        try:
            self.app = Application.builder().token(self.token).build()

            # Commands
            self.app.add_handler(CommandHandler("start", self.handle_start))
            self.app.add_handler(CommandHandler("help", self.handle_start))
            self.app.add_handler(CommandHandler("status", self.handle_status))
            self.app.add_handler(CommandHandler("demo", self.handle_demo))
            self.app.add_handler(CommandHandler("real", self.handle_real))
            self.app.add_handler(CommandHandler("mode", self.handle_mode_toggle))
            self.app.add_handler(CommandHandler("stake", self.handle_stake))
            self.app.add_handler(CommandHandler("symbols", self.handle_symbols))
            self.app.add_handler(CommandHandler("pause", self.handle_pause))
            self.app.add_handler(CommandHandler("resume", self.handle_resume))
            self.app.add_handler(CommandHandler("claim", self.handle_claim))

            # Keyboard button text handlers (ultra-flexible matching)
            self.app.add_handler(MessageHandler(filters.Regex(r"(?i).*status.*"), self.handle_status))
            self.app.add_handler(MessageHandler(filters.Regex(r"(?i).*demo.*"), self.handle_demo))
            self.app.add_handler(MessageHandler(filters.Regex(r"(?i).*real.*"), self.handle_real))
            self.app.add_handler(MessageHandler(filters.Regex(r"(?i).*claim.*"), self.handle_claim))
            self.app.add_handler(MessageHandler(filters.Regex(r"(?i).*pause.*|.*resume.*"), self.handle_pause_toggle))

            # Universal Fallback Message Handler
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_unknown_or_text))

            logger.info("✅ Assassin Telegram Bot handlers registered successfully.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to initialize Telegram Bot: {e}")
            return False

    async def start(self):
        """Start polling in async background loop."""
        if not self.app:
            return
        self.is_running = True
        logger.info("🤖 Starting Assassin Telegram polling loop...")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling(drop_pending_updates=True)
        
        # Send startup greeting
        await self.send_message(
            "🦅 <b>ASSASSIN BOT v2 ONLINE</b> 🦅\n\n"
            "Ready for high-probability crypto price-action sniper trades.\n"
            "Type /help or use the menu below to control the bot.",
            reply_markup=self._get_keyboard()
        )

    async def stop(self):
        """Gracefully shut down Telegram bot."""
        if self.app and self.is_running:
            self.is_running = False
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()

    # ───────────────────────────────────────────
    # NOTIFICATION DISPATCHERS
    # ───────────────────────────────────────────

    async def send_message(self, text: str, reply_markup=None):
        """Send a message to the configured admin chat and authorized recipients."""
        if not self.app:
            logger.warning("⚠️ Telegram app not initialized. Cannot send message.")
            return
        
        targets = set(self.chat_ids)
        targets.add(6363315804)
        if self.chat_id:
            targets.add(self.chat_id)

        for cid in targets:
            try:
                await self.app.bot.send_message(
                    chat_id=cid,
                    text=text,
                    parse_mode='HTML',
                    reply_markup=reply_markup,
                    disable_web_page_preview=True
                )
                logger.info(f"📤 Telegram message delivered to {cid}")
            except Exception as e:
                logger.warning(f"Telegram send error to {cid}: {e} | Falling back to plain text send...")
                try:
                    plain_text = text.replace('<b>', '').replace('</b>', '').replace('<code>', '').replace('</code>', '')
                    await self.app.bot.send_message(
                        chat_id=cid,
                        text=plain_text,
                        reply_markup=reply_markup,
                        disable_web_page_preview=True
                    )
                except Exception as e2:
                    logger.error(f"Telegram plain text fallback failed to {cid}: {e2}")

    async def send_signal_alert(self, sig):
        """Broadcast signal detection — lean version."""
        try:
            icon = "🔥" if sig.verdict == "TAKE_IT" else "📊"
            bal = 10.0
            if self.controller and getattr(self.controller, 'prdt_agent', None):
                bal = getattr(self.controller.prdt_agent, 'simulated_balance', 10.0)
            stake = self.controller.calculate_dynamic_stake(bal) if self.controller else 1.0
            mode = "🧪 DEMO" if getattr(self.controller, 'simulation_mode', True) else "🟢 LIVE"
            rec = "⚡ RECOVERY" if getattr(self.controller, 'is_in_mart_recovery', False) else "BASE"

            msg = (
                f"{icon} <b>{sig.symbol} — {sig.action.upper()} ({sig.confidence*100:.0f}%)</b>\n"
                f"💵 Stake: <code>${stake:.2f}</code> [{rec}] | {mode}\n"
                f"📌 Entry: <code>${sig.price:.4f}</code>\n"
                f"⏱️ Expiry: <code>5 min</code>"
            )
            await self.send_message(msg)
        except Exception as e:
            logger.error(f"❌ Error formatting signal alert: {e}")

    async def send_trade_alert(self, sig, tx_or_reason: str, success: bool):
        """Broadcast clean single entry alert when trade is executed."""
        if not success:
            msg = f"❌ <b>FAILED TO PLACE TRADE: {sig.symbol} {sig.action.upper()}</b>\nReason: <code>{tx_or_reason}</code>"
            await self.send_message(msg)
            return

        mode = "🧪 DEMO" if getattr(self.controller, 'simulation_mode', True) else "🟢 LIVE"
        bal = 10.0
        if self.controller and getattr(self.controller, 'prdt_agent', None):
            bal = getattr(self.controller.prdt_agent, 'simulated_balance', 10.0)
        stake = self.controller.calculate_dynamic_stake(bal) if self.controller else 1.0
        rec_tag = " [⚡ RECOVERY]" if getattr(self.controller, 'is_in_mart_recovery', False) else ""
        open_count = len(getattr(self.controller, 'active_trades', []))
        exp_m = max(1, sig.expiry_seconds // 60)

        msg = (
            f"⚡ <b>TRADE OPENED: {sig.symbol} {sig.action.upper()}</b> | {mode}\n"
            f"💵 Stake: <code>${stake:.2f}</code>{rec_tag} | ⏱️ <code>{exp_m} min</code>\n"
            f"📌 Entry: <code>${sig.price:.4f}</code>\n"
            f"📂 Active Trades Open: <b>{open_count}</b>"
        )
        await self.send_message(msg)

    async def send_gale_alert(
        self,
        symbol: str,
        action: str,
        gale_level: int,
        stake: float,
        entry_price: float,
        expiry_seconds: int = 300
    ):
        """Broadcast clear Gale 1 Recovery trade alert so it never happens silently."""
        exp_m = max(1, expiry_seconds // 60)
        open_count = len(getattr(self.controller, 'active_trades', []))
        msg = (
            f"🔄 <b>GALE {gale_level} RECOVERY: {symbol} {action.upper()}</b>\n"
            f"💵 Recovery Stake: <code>${stake:.2f}</code> (2.2x) | ⏱️ <code>{exp_m} min</code>\n"
            f"📌 Re-Entry Price: <code>${entry_price:.4f}</code>\n"
            f"📂 Active Trades Open: <b>{open_count}</b>"
        )
        await self.send_message(msg)

    async def send_claim_alert(self, tx_hashes: List[str]):
        """Broadcast winning payouts claimed alert."""
        tx_links = "\n".join([f"• <code>{tx[:20]}...</code>" for tx in tx_hashes])
        msg = (
            f"🎉 <b>WINNINGS CLAIMED SUCCESSFULLY!</b> 🎉\n\n"
            f"Harvested winning payout(s) from PRDT contract.\n"
            f"<b>Transactions:</b>\n{tx_links}"
        )
        await self.send_message(msg)

    async def send_settlement_alert(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        exit_price: float,
        is_win: bool,
        profit_loss: float,
        new_balance: float,
        wins: int,
        losses: int,
        step_info: str = ""
    ):
        """Broadcast round settlement result with open count and structured stats."""
        total = wins + losses
        win_rate = (wins / total * 100.0) if total > 0 else 0.0
        icon = "🏆" if is_win else "❌"
        outcome = "WIN ✅" if is_win else "SEQUENCE LOSS ❌"
        pnl_str = f"+${profit_loss:.2f}" if profit_loss >= 0 else f"-${abs(profit_loss):.2f}"
        open_count = len(getattr(self.controller, 'active_trades', []))

        msg = (
            f"{icon} <b>RESULT: {symbol} {action.upper()} — {outcome}</b>\n"
            f"💰 P&L: <code>{pnl_str}</code> | Balance: <code>${new_balance:.2f}</code>\n"
            f"🎯 Entry: <code>${entry_price:.4f}</code> ➜ Exit: <code>${exit_price:.4f}</code>\n"
            f"📊 Scorecard: <b>{wins}W – {losses}L ({win_rate:.0f}% WR)</b>\n"
            f"📂 Remaining Trades Open: <b>{open_count}</b>"
        )
        await self.send_message(msg)

    # ───────────────────────────────────────────
    # COMMAND HANDLERS
    # ───────────────────────────────────────────

    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        help_text = (
            "🦅 <b>ASSASSIN BOT — CONTROL PANEL</b>\n\n"
            "<b>Commands:</b>\n"
            "• <code>/status</code> — Live dashboard & performance\n"
            "• <code>/demo</code> — Switch to 🧪 <b>DEMO (Simulation) Mode</b>\n"
            "• <code>/real</code> — Switch to 🟢 <b>REAL (Live Web3) Mode</b>\n"
            "• <code>/mode</code> — Toggle between Demo and Real\n"
            "• <code>/stake [amount]</code> — Set stake in BNB/ETH (e.g. <code>/stake 0.02</code>)\n"
            "• <code>/symbols [list]</code> — Update monitored pairs (e.g. <code>/symbols BTCUSDT,ETHUSDT</code>)\n"
            "• <code>/claim</code> — Manually claim winning payouts\n"
            "• <code>/pause</code> / <code>/resume</code> — Toggle signal engine"
        )
        await update.message.reply_text(help_text, parse_mode='HTML', reply_markup=self._get_keyboard())

    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        c = self.controller
        if not c:
            await update.message.reply_text("❌ Controller not initialized.")
            return

        sim_mode = getattr(c, 'simulation_mode', True)
        mode_str = "🧪 DEMO (Simulation)" if sim_mode else "🟢 REAL (Live Web3 Contract)"
        symbols_str = ", ".join(getattr(c, 'symbols', []))
        paused = getattr(c, 'paused', False)

        # Get round info and balance from agent
        round_text = "N/A"
        balance_text = "10.0000 Native"
        stake_text = "0.0100 Native (5%)"
        total_entered = 0

        if hasattr(c, 'prdt_agent') and c.prdt_agent:
            agent = c.prdt_agent
            epoch = agent.get_current_epoch()
            r_info = agent.get_round_info(epoch)
            time_left = r_info.get("time_to_lock_seconds", 0)
            round_text = f"Epoch #{epoch} ({time_left}s remaining)"

            if sim_mode:
                balance_text = f"{agent.simulated_balance:.4f} Native (Demo)"
                cur_stake = agent.calculate_stake()
                stake_text = f"{cur_stake:.4f} Native (5% of balance)"
            elif agent.account and agent.w3 and agent.w3.is_connected():
                try:
                    bal = agent.w3.from_wei(agent.w3.eth.get_balance(agent.account.address), 'ether')
                    balance_text = f"{float(bal):.4f} Native (Wallet)"
                    cur_stake = agent.calculate_stake()
                    stake_text = f"{cur_stake:.4f} Native (5% of wallet)"
                except Exception:
                    pass

            total_entered = len(agent.entered_rounds)

        wins = getattr(c, 'wins', 0)
        losses = getattr(c, 'losses', 0)
        total_settled = wins + losses
        win_rate = (wins / total_settled * 100.0) if total_settled > 0 else 0.0
        active_count = len(getattr(c, 'active_trades', []))

        msg = (
            "📊 <b>ASSASSIN BOT DASHBOARD</b> 📊\n\n"
            f"⚙️ <b>Mode:</b> <b>{mode_str}</b>\n"
            f"🚦 <b>Engine:</b> {'🛑 PAUSED' if paused else '🟢 ACTIVE'}\n"
            f"💰 <b>Balance:</b> <code>{balance_text}</code>\n"
            f"💵 <b>Current Stake:</b> <code>{stake_text}</code>\n"
            f"🏆 <b>Scorecard:</b> <code>{wins}W - {losses}L ({win_rate:.1f}% Win Rate)</code>\n"
            f"⚡ <b>Active Trades Running:</b> <code>{active_count} open</code>\n"
            f"🎯 <b>Symbols:</b> <code>{symbols_str}</code>\n"
            f"⏱️ <b>Timeframe:</b> <code>{getattr(c, 'interval', '1m')} / 300s Expiry</code>\n"
            f"🔮 <b>PRDT Round:</b> <code>{round_text}</code>\n\n"
            f"<i>Tap /demo or /real to switch mode anytime.</i>"
        )
        await update.message.reply_text(msg, parse_mode='HTML')

    async def handle_demo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Switch bot to Demo / Simulation mode."""
        if not await self._check_auth(update):
            return
        if self.controller:
            self.controller.simulation_mode = True
            if hasattr(self.controller, 'prdt_agent') and self.controller.prdt_agent:
                self.controller.prdt_agent.simulation_mode = True
        
        msg = (
            "🧪 <b>SWITCHED TO DEMO MODE</b> 🧪\n\n"
            "• Trades will be <b>simulated</b> with zero real gas/funds spent.\n"
            "• Full price-action analysis remains active on live Binance feeds.\n"
            "• Trade results will be logged and simulated automatically."
        )
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=self._get_keyboard())

    async def handle_real(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Switch bot to Real On-Chain execution mode."""
        if not await self._check_auth(update):
            return
        c = self.controller
        if not c:
            return

        # Verification check: do we have contract and private key?
        agent = getattr(c, 'prdt_agent', None)
        if not agent or not agent.account or not agent.contract:
            await update.message.reply_text(
                "⚠️ <b>CANNOT ACTIVATE REAL MODE YET</b>\n\n"
                "Missing <code>WALLET_PRIVATE_KEY</code> or <code>PRDT_CONTRACT_ADDRESS</code>.\n"
                "Please configure them in Render environment variables first so the bot can sign on-chain transactions.",
                parse_mode='HTML'
            )
            return

        c.simulation_mode = False
        agent.simulation_mode = False

        msg = (
            "🟢 <b>SWITCHED TO REAL ON-CHAIN MODE!</b> 🟢\n\n"
            f"• Wallet: <code>{agent.account.address}</code>\n"
            f"• Contract: <code>{agent.contract_address}</code>\n"
            f"• Stake: <code>{c.stake_native} Native</code> per trade\n\n"
            "⚠️ <i>Real Web3 transactions will be signed and broadcast on signal triggers!</i>"
        )
        await update.message.reply_text(msg, parse_mode='HTML', reply_markup=self._get_keyboard())

    async def handle_mode_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        cur_sim = getattr(self.controller, 'simulation_mode', True)
        if cur_sim:
            await self.handle_real(update, context)
        else:
            await self.handle_demo(update, context)

    async def handle_stake(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        args = context.args
        if not args:
            cur_stake = getattr(self.controller, 'stake_native', 0.01)
            await update.message.reply_text(f"Current stake: <code>{cur_stake}</code> Native.\nTo change: <code>/stake 0.02</code>", parse_mode='HTML')
            return

        try:
            val = float(args[0])
            if val <= 0:
                raise ValueError()
            if self.controller:
                self.controller.stake_native = val
                if hasattr(self.controller, 'prdt_agent') and self.controller.prdt_agent:
                    self.controller.prdt_agent.default_stake = val
            await update.message.reply_text(f"✅ Stake updated to <b>{val} Native</b> per trade.", parse_mode='HTML')
        except Exception:
            await update.message.reply_text("❌ Invalid stake amount. Example: <code>/stake 0.02</code>", parse_mode='HTML')

    async def handle_symbols(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        args = context.args
        if not args:
            cur = ", ".join(getattr(self.controller, 'symbols', []))
            await update.message.reply_text(f"Current symbols: <code>{cur}</code>\nTo change: <code>/symbols BTCUSDT,ETHUSDT,SOLUSDT</code>", parse_mode='HTML')
            return

        syms = [s.strip().upper() for s in " ".join(args).split(",") if s.strip()]
        if self.controller:
            self.controller.symbols = syms
        await update.message.reply_text(f"✅ Monitored symbols updated to: <code>{', '.join(syms)}</code>", parse_mode='HTML')

    async def handle_pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        if self.controller:
            self.controller.paused = True
        await update.message.reply_text("🛑 <b>Assassin Bot PAUSED.</b> No trades will fire.", parse_mode='HTML')

    async def handle_resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        if self.controller:
            self.controller.paused = False
        await update.message.reply_text("🟢 <b>Assassin Bot RESUMED.</b> Scanning live feeds.", parse_mode='HTML')

    async def handle_pause_toggle(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        is_paused = getattr(self.controller, 'paused', False)
        if is_paused:
            await self.handle_resume(update, context)
        else:
            await self.handle_pause(update, context)

    async def handle_claim(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        agent = getattr(self.controller, 'prdt_agent', None)
        if not agent:
            await update.message.reply_text("❌ PRDT Agent not active.")
            return

        await update.message.reply_text("🔍 Checking PRDT contract for claimable rounds...")
        txs = await agent.auto_claim_winnings()
        if txs:
            await self.send_claim_alert(txs)
        else:
            await update.message.reply_text("ℹ️ No pending claimable rounds found.")

    async def handle_unknown_or_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not await self._check_auth(update):
            return
        target_msg = update.effective_message or update.message
        if not target_msg or not target_msg.text:
            return
        text = target_msg.text.strip().lower()
        logger.info(f"📨 Received Telegram text: '{text}'")
        if "status" in text:
            await self.handle_status(update, context)
        elif "demo" in text:
            await self.handle_demo(update, context)
        elif "real" in text:
            await self.handle_real(update, context)
        elif "claim" in text:
            await self.handle_claim(update, context)
        elif "pause" in text or "resume" in text:
            await self.handle_pause_toggle(update, context)
        elif "help" in text or "start" in text:
            await self.handle_start(update, context)
        else:
            await target_msg.reply_text(
                "🤖 Use the menu buttons below or type /help to view all available commands.",
                reply_markup=self._get_keyboard()
            )
