"""
Margin of Safety & Pending State Execution Filter
=================================================
Calculates psychological round numbers, support/resistance reaction zones,
and enforces a wait-state/pending-retest execution model for high win rates.
"""
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import math


@dataclass
class PendingSetup:
    setup_id: str
    symbol: str
    action: str  # 'call' or 'put'
    armed_price: float
    target_safety_level: float
    tolerance_pct: float
    trigger_source: str
    created_timestamp: float
    created_candle_idx: int
    expiry_candles: int = 5
    is_triggered: bool = False
    is_expired: bool = False


class MarginOfSafetyFilter:
    def __init__(self, tolerance_pct: float = 0.08, max_wait_candles: int = 5):
        """
        Args:
            tolerance_pct: Percentage buffer around key level to confirm a touch/rejection (default 0.08%).
            max_wait_candles: Maximum candles to wait for retest before canceling setup.
        """
        self.tolerance_pct = tolerance_pct
        self.max_wait_candles = max_wait_candles
        self.pending_setups: Dict[str, List[PendingSetup]] = {}

    @staticmethod
    def get_round_number_step(price: float) -> float:
        """Dynamically determine round number interval based on asset price magnitude."""
        if price >= 10000:       # BTC scale (~$60k-$90k)
            return 100.0         # e.g., 68500, 68600
        elif price >= 1000:      # ETH scale (~$2k-$4k)
            return 25.0          # e.g., 2500, 2525, 2550
        elif price >= 100:       # SOL / BNB scale (~$100-$600)
            return 5.0           # e.g., 140, 145, 150
        elif price >= 10:
            return 1.0
        elif price >= 1.0:
            return 0.10
        else:
            return 0.01

    @staticmethod
    def find_nearest_round_numbers(price: float, step: Optional[float] = None) -> Tuple[float, float]:
        """Find the immediate round numbers above and below the given price."""
        if step is None:
            step = MarginOfSafetyFilter.get_round_number_step(price)
        lower = math.floor(price / step) * step
        upper = math.ceil(price / step) * step
        return lower, upper

    def is_at_safety_level(self, current_price: float, target_level: float, tolerance: Optional[float] = None) -> bool:
        """Check if current price has touched or is within safety margin of the target level."""
        if tolerance is None:
            tolerance = self.tolerance_pct
        diff_pct = abs(current_price - target_level) / target_level * 100.0 if target_level > 0 else 999.0
        return diff_pct <= tolerance

    def arm_setup(
        self,
        setup_id: str,
        symbol: str,
        action: str,
        current_price: float,
        safety_level: float,
        trigger_source: str,
        timestamp: float,
        candle_idx: int
    ) -> PendingSetup:
        """Arm a pending setup waiting for price to touch the margin of safety level."""
        if symbol not in self.pending_setups:
            self.pending_setups[symbol] = []

        setup = PendingSetup(
            setup_id=setup_id,
            symbol=symbol,
            action=action,
            armed_price=current_price,
            target_safety_level=safety_level,
            tolerance_pct=self.tolerance_pct,
            trigger_source=trigger_source,
            created_timestamp=timestamp,
            created_candle_idx=candle_idx,
            expiry_candles=self.max_wait_candles
        )
        self.pending_setups[symbol].append(setup)
        return setup

    def check_pending(self, symbol: str, current_price: float, current_candle_idx: int) -> List[PendingSetup]:
        """
        Check all active pending setups for symbol against current price.
        Returns all setups that have successfully reached their margin-of-safety level.
        """
        if symbol not in self.pending_setups:
            return []

        ready_to_execute: List[PendingSetup] = []
        still_pending: List[PendingSetup] = []

        for setup in self.pending_setups[symbol]:
            # Check expiration
            if current_candle_idx - setup.created_candle_idx > setup.expiry_candles:
                setup.is_expired = True
                continue

            # Check if price has touched / retraced to safety level
            if self.is_at_safety_level(current_price, setup.target_safety_level, setup.tolerance_pct):
                setup.is_triggered = True
                ready_to_execute.append(setup)
            else:
                still_pending.append(setup)

        self.pending_setups[symbol] = still_pending
        return ready_to_execute
