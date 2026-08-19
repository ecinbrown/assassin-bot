"""
Quasimodo (QM) Pattern & Order Block Module
===========================================
Detects Quasimodo market structure sequences (L-H-LL-HH and H-L-HH-LL),
identifies associated Order Blocks, and cross-references Fair Value Gaps.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple
from .candle_utils import Candle
from .swing_detector import SwingPoint, SwingDetector
from .fvg_detector import FVG


@dataclass
class OrderBlock:
    ob_type: str  # 'bullish' (Demand) or 'bearish' (Supply)
    zone_low: float
    zone_high: float
    center: float
    candle_idx: int
    timestamp: float


@dataclass
class QMPattern:
    pattern_type: str  # 'bullish' (CALL bias) or 'bearish' (PUT bias)
    p1: SwingPoint  # L1 or H1
    p2: SwingPoint  # H1 or L1
    p3: SwingPoint  # LL or HH
    p4: SwingPoint  # HH or LL
    order_block: OrderBlock
    qm_level: float  # The key price level to retest (P1 price)
    fvg_confluence: Optional[FVG] = None
    confirmed_idx: int = 0


class QMPatternDetector:
    def __init__(self, swing_left: int = 2, swing_right: int = 2, max_pattern_age: int = 40):
        self.swing_detector = SwingDetector(left_bars=swing_left, right_bars=swing_right)
        self.max_pattern_age = max_pattern_age

    def detect_qm(self, candles: List[Candle], active_fvgs: Optional[List[FVG]] = None) -> List[QMPattern]:
        """
        Scan candle history for confirmed QM sequences and matching Order Blocks.
        """
        patterns: List[QMPattern] = []
        swings = self.swing_detector.find_swings(candles)
        if len(swings) < 4:
            return patterns

        n_swings = len(swings)
        current_idx = len(candles) - 1

        # Evaluate the 4 most recent alternating swing points
        for i in range(n_swings - 4, n_swings - 3):
            if i < 0:
                continue

            s1, s2, s3, s4 = swings[i], swings[i+1], swings[i+2], swings[i+3]

            # 1. Bullish QM: Low (s1) -> High (s2) -> Lower Low (s3) -> Higher High (s4)
            if (s1.is_low and s2.is_high and s3.is_low and s4.is_high):
                if s3.price < s1.price and s4.price > s2.price:
                    # Confirmed Bullish QM structure!
                    # Find Order Block: The lowest down-candle around s3 before the impulsive rally to s4
                    ob_candle_idx = s3.index
                    ob_low = candles[ob_candle_idx].low
                    ob_high = candles[ob_candle_idx].high
                    
                    ob = OrderBlock(
                        ob_type='bullish',
                        zone_low=ob_low,
                        zone_high=ob_high,
                        center=(ob_low + ob_high) / 2.0,
                        candle_idx=ob_candle_idx,
                        timestamp=candles[ob_candle_idx].timestamp
                    )

                    # Check FVG Confluence
                    matching_fvg = None
                    if active_fvgs:
                        for fvg in active_fvgs:
                            if fvg.fvg_type == 'bullish' and fvg.overlaps_zone(ob_low, max(ob_high, s1.price)):
                                matching_fvg = fvg
                                break

                    pattern = QMPattern(
                        pattern_type='bullish',
                        p1=s1,
                        p2=s2,
                        p3=s3,
                        p4=s4,
                        order_block=ob,
                        qm_level=s1.price,
                        fvg_confluence=matching_fvg,
                        confirmed_idx=s4.index
                    )
                    patterns.append(pattern)

            # 2. Bearish QM: High (s1) -> Low (s2) -> Higher High (s3) -> Lower Low (s4)
            elif (s1.is_high and s2.is_low and s3.is_high and s4.is_low):
                if s3.price > s1.price and s4.price < s2.price:
                    # Confirmed Bearish QM structure!
                    # Find Order Block: The highest up-candle around s3 before the drop to s4
                    ob_candle_idx = s3.index
                    ob_low = candles[ob_candle_idx].low
                    ob_high = candles[ob_candle_idx].high
                    
                    ob = OrderBlock(
                        ob_type='bearish',
                        zone_low=ob_low,
                        zone_high=ob_high,
                        center=(ob_low + ob_high) / 2.0,
                        candle_idx=ob_candle_idx,
                        timestamp=candles[ob_candle_idx].timestamp
                    )

                    # Check FVG Confluence
                    matching_fvg = None
                    if active_fvgs:
                        for fvg in active_fvgs:
                            if fvg.fvg_type == 'bearish' and fvg.overlaps_zone(min(ob_low, s1.price), ob_high):
                                matching_fvg = fvg
                                break

                    pattern = QMPattern(
                        pattern_type='bearish',
                        p1=s1,
                        p2=s2,
                        p3=s3,
                        p4=s4,
                        order_block=ob,
                        qm_level=s1.price,
                        fvg_confluence=matching_fvg,
                        confirmed_idx=s4.index
                    )
                    patterns.append(pattern)

        return patterns
