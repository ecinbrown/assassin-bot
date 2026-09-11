"""
Candle Utilities & Gap Detection Module
=======================================
Provides core candle math, body/range ratios, and inter-candle gap detection.
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class Candle:
    timestamp: float
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    trades: float = 1.0


    @property
    def body_size(self) -> float:
        """Absolute height of candle body."""
        return abs(self.close - self.open)

    @property
    def total_range(self) -> float:
        """High minus low range."""
        return self.high - self.low

    @property
    def body_ratio(self) -> float:
        """Body size as a fraction of total candle range (0.0 to 1.0)."""
        rng = self.total_range
        return self.body_size / rng if rng > 0 else 0.0

    @property
    def upper_wick(self) -> float:
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        return min(self.open, self.close) - self.low

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def is_flat(self) -> bool:
        return self.close == self.open


def detect_gap(current: Candle, previous: Candle) -> Tuple[str, float, float]:
    """
    Detect price gap between previous candle close and current candle open.
    
    Returns:
        (gap_type, gap_size, gap_pct)
        where gap_type in ('gap_up', 'gap_down', 'none')
    """
    if previous.close == 0:
        return 'none', 0.0, 0.0

    diff = current.open - previous.close
    gap_size = abs(diff)
    gap_pct = (gap_size / previous.close) * 100.0

    # Minimal threshold for crypto tick noise (0.005%)
    if diff > 0 and gap_pct >= 0.005:
        return 'gap_up', gap_size, gap_pct
    elif diff < 0 and gap_pct >= 0.005:
        return 'gap_down', gap_size, gap_pct

    return 'none', gap_size, gap_pct
