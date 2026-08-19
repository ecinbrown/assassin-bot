"""
Swing & Fractal Structure Detection Module
==========================================
Identifies swing highs and swing lows using multi-bar fractal logic
for market structure mapping and Quasimodo pattern identification.
"""
from dataclasses import dataclass
from typing import List, Optional
from .candle_utils import Candle


@dataclass
class SwingPoint:
    index: int
    timestamp: float
    price: float
    point_type: str  # 'SH' (Swing High) or 'SL' (Swing Low)

    @property
    def is_high(self) -> bool:
        return self.point_type == 'SH'

    @property
    def is_low(self) -> bool:
        return self.point_type == 'SL'


class SwingDetector:
    def __init__(self, left_bars: int = 2, right_bars: int = 2):
        """
        Args:
            left_bars: Number of candles required to the left with lower highs/higher lows.
            right_bars: Number of candles required to the right to confirm the pivot.
        """
        self.left_bars = left_bars
        self.right_bars = right_bars
        self.required_window = left_bars + right_bars + 1

    def find_swings(self, candles: List[Candle]) -> List[SwingPoint]:
        """
        Scan a list of candles and return confirmed swing points in chronological order.
        """
        swings: List[SwingPoint] = []
        n = len(candles)
        if n < self.required_window:
            return swings

        for i in range(self.left_bars, n - self.right_bars):
            curr = candles[i]
            
            # Check for Swing High
            is_sh = True
            for l in range(1, self.left_bars + 1):
                if candles[i - l].high >= curr.high:
                    is_sh = False
                    break
            if is_sh:
                for r in range(1, self.right_bars + 1):
                    if candles[i + r].high > curr.high:
                        is_sh = False
                        break
            if is_sh:
                swings.append(SwingPoint(
                    index=i,
                    timestamp=curr.timestamp,
                    price=curr.high,
                    point_type='SH'
                ))
                continue

            # Check for Swing Low
            is_sl = True
            for l in range(1, self.left_bars + 1):
                if candles[i - l].low <= curr.low:
                    is_sl = False
                    break
            if is_sl:
                for r in range(1, self.right_bars + 1):
                    if candles[i + r].low < curr.low:
                        is_sl = False
                        break
            if is_sl:
                swings.append(SwingPoint(
                    index=i,
                    timestamp=curr.timestamp,
                    price=curr.low,
                    point_type='SL'
                ))

        return swings
