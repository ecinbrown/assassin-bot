"""
Fair Value Gap (FVG) Detection Module
=====================================
Detects 3-candle price imbalances (Fair Value Gaps), tracks unfilled
imbalance zones, and tests price mitigation for confluence zones.
"""
from dataclasses import dataclass
from typing import List, Optional
from .candle_utils import Candle


@dataclass
class FVG:
    fvg_type: str  # 'bullish' or 'bearish'
    zone_low: float
    zone_high: float
    center: float
    candle_idx: int
    timestamp: float
    mitigated: bool = False

    @property
    def size(self) -> float:
        return self.zone_high - self.zone_low

    def is_price_inside(self, price: float) -> bool:
        return self.zone_low <= price <= self.zone_high

    def overlaps_zone(self, low: float, high: float) -> bool:
        """Check if this FVG overlaps with another price zone (e.g. an Order Block)."""
        return max(self.zone_low, low) <= min(self.zone_high, high)


class FVGDetector:
    def __init__(self, min_gap_pct: float = 0.01, max_fvg_age: int = 50):
        """
        Args:
            min_gap_pct: Minimum gap size as % of price to filter noise.
            max_fvg_age: Max candles before an unfilled FVG is retired.
        """
        self.min_gap_pct = min_gap_pct
        self.max_fvg_age = max_fvg_age

    def scan_fvgs(self, candles: List[Candle]) -> List[FVG]:
        """
        Scans candle history and returns all active (unmitigated) Fair Value Gaps.
        """
        active_fvgs: List[FVG] = []
        n = len(candles)
        if n < 3:
            return active_fvgs

        for i in range(2, n):
            c1 = candles[i - 2]
            c2 = candles[i - 1]
            c3 = candles[i]

            # 1. Bullish FVG: Candle 3 Low > Candle 1 High
            if c3.low > c1.high:
                gap_size = c3.low - c1.high
                pct = (gap_size / c1.high) * 100.0 if c1.high > 0 else 0
                if pct >= self.min_gap_pct:
                    fvg = FVG(
                        fvg_type='bullish',
                        zone_low=c1.high,
                        zone_high=c3.low,
                        center=(c1.high + c3.low) / 2.0,
                        candle_idx=i,
                        timestamp=c3.timestamp,
                        mitigated=False
                    )
                    active_fvgs.append(fvg)

            # 2. Bearish FVG: Candle 3 High < Candle 1 Low
            elif c3.high < c1.low:
                gap_size = c1.low - c3.high
                pct = (gap_size / c1.low) * 100.0 if c1.low > 0 else 0
                if pct >= self.min_gap_pct:
                    fvg = FVG(
                        fvg_type='bearish',
                        zone_low=c3.high,
                        zone_high=c1.low,
                        center=(c3.high + c1.low) / 2.0,
                        candle_idx=i,
                        timestamp=c3.timestamp,
                        mitigated=False
                    )
                    active_fvgs.append(fvg)

        # Check subsequent candles for mitigation
        current_idx = n - 1
        unmitigated: List[FVG] = []
        for fvg in active_fvgs:
            if current_idx - fvg.candle_idx > self.max_fvg_age:
                continue

            # Check if any candle after FVG creation entered the zone
            mitigated = False
            for k in range(fvg.candle_idx + 1, n):
                ck = candles[k]
                if fvg.fvg_type == 'bullish' and ck.low <= fvg.zone_high:
                    mitigated = True
                    break
                elif fvg.fvg_type == 'bearish' and ck.high >= fvg.zone_low:
                    mitigated = True
                    break

            fvg.mitigated = mitigated
            if not mitigated:
                unmitigated.append(fvg)

        return unmitigated
