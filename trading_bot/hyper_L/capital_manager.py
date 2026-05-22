"""
═══════════════════════════════════════════════════════════════
  CAPITAL MANAGER: Dynamic Position Sizing & Compounding Engine
  
  Manages any starting balance. Automatically scales position 
  sizes, tracks P&L, enforces risk limits, and handles the 
  phase transitions (Assassin → Whale) as the account grows.
═══════════════════════════════════════════════════════════════
"""
import os
import json
import time
import logging
from datetime import datetime, timezone

logger = logging.getLogger('CapitalManager')

STATE_FILE = os.path.join(os.path.dirname(__file__), "capital_state.json")

# ═══════════════════════════════════════════
# STRATEGY CONFIGURATIONS
# ═══════════════════════════════════════════
STRATEGIES = {
    "ASSASSIN": {
        "name": "The Assassin",
        "tp_usd": 500,      # Take-Profit: $500 per BTC
        "sl_usd": 50,       # Stop-Loss: $50 per BTC
        "rr_ratio": 1.5,
        "min_confirmations": 2,
        "min_wick_ratio": 2.0,
        "verified_wr": 53.8,
        "max_account_size": 100_000_000,  # Switch to Whale above $100M
    },
    "WHALE": {
        "name": "The Whale",
        "tp_usd": 100,     # Take-Profit: $100 per BTC
        "sl_usd": 5,       # Stop-Loss: $5 per BTC
        "rr_ratio": 20.0,
        "min_confirmations": 3,
        "min_wick_ratio": 3.0,
        "verified_wr": 22.3,
        "max_account_size": float('inf'),
    },
}

class CapitalManager:
    """Manages position sizing, compounding, P&L tracking, and strategy selection."""
    
    def __init__(self, starting_balance: float, risk_pct: float = 0.01, leverage: int = 50):
        """
        Args:
            starting_balance: Initial USDC balance on Hyperliquid.
            risk_pct: Fraction of account to risk per trade (default 1%).
            leverage: Max leverage to use (default 50x).
        """
        self.balance = starting_balance
        self.initial_balance = starting_balance
        self.risk_pct = risk_pct
        self.leverage = leverage
        
        # Strategy auto-selection based on account size
        self.active_strategy = self._select_strategy()
        
        # Trade tracking
        self.total_trades = 0
        self.wins = 0
        self.losses = 0
        self.total_pnl = 0.0
        self.peak_balance = starting_balance
        self.max_drawdown = 0.0
        self.daily_trades = 0
        self.daily_pnl = 0.0
        self.current_day = datetime.now(timezone.utc).date()
        
        # Losing streak tracking
        self.current_losing_streak = 0
        self.max_losing_streak = 0
        
        # Trade history (last 100)
        self.trade_history = []
        
        # Risk circuit breakers
        self.MAX_DAILY_TRADES = 500
        self.MAX_DAILY_LOSS_PCT = 0.05  # Halt if 5% daily loss
        self.MAX_LOSING_STREAK = 20     # Halt if 20 consecutive losses
        
        # Load previous state if it exists
        self._load_state()
        
        logger.info(f"💰 Capital Manager Initialized")
        logger.info(f"   Balance:   ${self.balance:,.2f}")
        logger.info(f"   Risk:      {self.risk_pct*100:.1f}% per trade")
        logger.info(f"   Leverage:  {self.leverage}x")
        logger.info(f"   Strategy:  {self.active_strategy['name']}")
    
    def _select_strategy(self) -> dict:
        """Auto-select strategy based on current account size."""
        if self.balance <= STRATEGIES["ASSASSIN"]["max_account_size"]:
            return STRATEGIES["ASSASSIN"]
        else:
            return STRATEGIES["WHALE"]
    
    def get_strategy_params(self) -> dict:
        """Return the active strategy's signal parameters."""
        return {
            'min_confirmations': self.active_strategy['min_confirmations'],
            'min_wick_ratio': self.active_strategy['min_wick_ratio'],
            'tp_usd': self.active_strategy['tp_usd'],
            'sl_usd': self.active_strategy['sl_usd'],
        }
    
    def calculate_position_size(self, btc_price: float, dynamic_sl_usd: float = None) -> float:
        """
        Calculate exact BTC position size based on current balance and risk.
        
        Risk formula:
            risk_usd = balance * risk_pct
            position_btc = risk_usd / sl_usd
        
        Returns:
            Position size in BTC (e.g., 2.5 BTC)
        """
        sl_usd = dynamic_sl_usd if dynamic_sl_usd else self.active_strategy['sl_usd']
        risk_usd = self.balance * self.risk_pct
        position_btc = risk_usd / sl_usd
        
        # Cap by leverage: max_notional = balance * leverage
        max_notional = self.balance * self.leverage
        max_btc_by_leverage = max_notional / btc_price
        
        position_btc = min(position_btc, max_btc_by_leverage)
        
        # Hyperliquid minimum size
        if position_btc < 0.001:
            position_btc = 0.001
        
        # Round to 3 decimal places (Hyperliquid precision)
        position_btc = round(position_btc, 3)
        
        logger.info(
            f"📐 Position Calc: Balance=${self.balance:,.0f} | "
            f"Risk=${risk_usd:,.0f} ({self.risk_pct*100:.1f}%) | "
            f"Size={position_btc:.3f} BTC (${position_btc * btc_price:,.0f} notional)"
        )
        
        return position_btc
    
    def calculate_tp_sl_prices(self, entry_price: float, is_long: bool) -> tuple:
        """
        Calculate exact TP and SL prices for a trade.
        
        Returns:
            (tp_price, sl_price)
        """
        tp_usd = self.active_strategy['tp_usd']
        sl_usd = self.active_strategy['sl_usd']
        
        if is_long:
            tp_price = entry_price + tp_usd
            sl_price = entry_price - sl_usd
        else:
            tp_price = entry_price - tp_usd
            sl_price = entry_price + sl_usd
        
        return (round(tp_price, 1), round(sl_price, 1))
    
    def record_trade(self, pnl: float, direction: str, entry: float, exit_price: float):
        """Record a completed trade and update all statistics."""
        self.total_trades += 1
        self.total_pnl += pnl
        self.balance += pnl
        
        won = pnl > 0
        if won:
            self.wins += 1
            self.current_losing_streak = 0
        else:
            self.losses += 1
            self.current_losing_streak += 1
            self.max_losing_streak = max(self.max_losing_streak, self.current_losing_streak)
        
        # Peak / drawdown tracking
        if self.balance > self.peak_balance:
            self.peak_balance = self.balance
        dd = (self.peak_balance - self.balance) / self.peak_balance * 100
        self.max_drawdown = max(self.max_drawdown, dd)
        
        # Daily tracking
        today = datetime.now(timezone.utc).date()
        if today != self.current_day:
            self.daily_trades = 0
            self.daily_pnl = 0.0
            self.current_day = today
        self.daily_trades += 1
        self.daily_pnl += pnl
        
        # Auto-switch strategy if balance crossed threshold
        old_strategy = self.active_strategy['name']
        self.active_strategy = self._select_strategy()
        if self.active_strategy['name'] != old_strategy:
            logger.critical(
                f"🔄 STRATEGY SWITCH: {old_strategy} → {self.active_strategy['name']} "
                f"(Balance crossed ${STRATEGIES['ASSASSIN']['max_account_size']:,.0f})"
            )
        
        # Trade history
        self.trade_history.append({
            'time': datetime.now(timezone.utc).isoformat(),
            'direction': direction,
            'entry': entry,
            'exit': exit_price,
            'pnl': pnl,
            'balance': self.balance,
        })
        if len(self.trade_history) > 100:
            self.trade_history = self.trade_history[-100:]
        
        # Save state after every trade
        self._save_state()
        
        icon = "✅" if won else "❌"
        wr = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0
        logger.info(
            f"{icon} Trade #{self.total_trades}: {direction} | "
            f"PnL: ${pnl:+,.2f} | Balance: ${self.balance:,.2f} | "
            f"WR: {wr:.1f}% ({self.wins}W/{self.losses}L) | "
            f"Total PnL: ${self.total_pnl:+,.2f}"
        )
    
    def can_trade(self) -> tuple:
        """
        Check if trading is allowed based on risk circuit breakers.
        
        Returns:
            (allowed: bool, reason: str)
        """
        # Check daily trade limit
        if self.daily_trades >= self.MAX_DAILY_TRADES:
            return (False, f"Daily trade limit reached ({self.MAX_DAILY_TRADES})")
        
        # Check daily loss limit
        daily_loss_pct = abs(self.daily_pnl / self.balance) if self.daily_pnl < 0 else 0
        if daily_loss_pct >= self.MAX_DAILY_LOSS_PCT:
            return (False, f"Daily loss limit hit ({daily_loss_pct*100:.1f}% >= {self.MAX_DAILY_LOSS_PCT*100:.0f}%)")
        
        # Check losing streak
        if self.current_losing_streak >= self.MAX_LOSING_STREAK:
            return (False, f"Max losing streak hit ({self.current_losing_streak} consecutive losses)")
        
        # Check minimum balance
        if self.balance < 10:
            return (False, f"Balance too low (${self.balance:.2f})")
        
        return (True, "OK")
    
    def get_status(self) -> dict:
        """Return current status summary."""
        wr = (self.wins / self.total_trades * 100) if self.total_trades > 0 else 0
        return {
            'balance': self.balance,
            'initial_balance': self.initial_balance,
            'total_return_pct': ((self.balance - self.initial_balance) / self.initial_balance * 100),
            'total_pnl': self.total_pnl,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'win_rate': wr,
            'peak_balance': self.peak_balance,
            'max_drawdown_pct': self.max_drawdown,
            'max_losing_streak': self.max_losing_streak,
            'current_losing_streak': self.current_losing_streak,
            'daily_trades': self.daily_trades,
            'daily_pnl': self.daily_pnl,
            'active_strategy': self.active_strategy['name'],
        }
    
    def _save_state(self):
        """Persist state to disk for crash recovery."""
        state = {
            'balance': self.balance,
            'initial_balance': self.initial_balance,
            'risk_pct': self.risk_pct,
            'leverage': self.leverage,
            'total_trades': self.total_trades,
            'wins': self.wins,
            'losses': self.losses,
            'total_pnl': self.total_pnl,
            'peak_balance': self.peak_balance,
            'max_drawdown': self.max_drawdown,
            'max_losing_streak': self.max_losing_streak,
            'current_losing_streak': self.current_losing_streak,
            'trade_history': self.trade_history[-20:],  # Save last 20
            'saved_at': datetime.now(timezone.utc).isoformat(),
        }
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
    
    def _load_state(self):
        """Load previous state from disk if available."""
        if not os.path.exists(STATE_FILE):
            return
        
        try:
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            
            self.balance = state.get('balance', self.balance)
            self.initial_balance = state.get('initial_balance', self.initial_balance)
            self.total_trades = state.get('total_trades', 0)
            self.wins = state.get('wins', 0)
            self.losses = state.get('losses', 0)
            self.total_pnl = state.get('total_pnl', 0.0)
            self.peak_balance = state.get('peak_balance', self.balance)
            self.max_drawdown = state.get('max_drawdown', 0.0)
            self.max_losing_streak = state.get('max_losing_streak', 0)
            self.current_losing_streak = state.get('current_losing_streak', 0)
            self.trade_history = state.get('trade_history', [])
            
            self.active_strategy = self._select_strategy()
            
            logger.info(f"📂 Loaded previous state: {self.total_trades} trades, ${self.balance:,.2f} balance")
        except Exception as e:
            logger.warning(f"Could not load state: {e}. Starting fresh.")
