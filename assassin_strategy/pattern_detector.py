"""
Candlestick Pattern Detection Module
=====================================
Implements pure price-action pattern detection from the Assassin Analyzer:
  1. Exhaustion Candle: Long wick, tiny body opposite trend, bigger range than recent candles
  2. Engulfing: Current body fully swallows prior body, at a key level
  3. Spinning Top: Small body, wicks both sides — expect pause
  4. Third Touch Breakout: Trendline with 2 prior touches, 3rd touch/break is trigger
"""
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from .candle_utils import Candle


@dataclass
class PatternSignal:
    pattern: str           # e.g. 'EXHAUSTION', 'ENGULFING', 'SPINNING_TOP', 'THIRD_TOUCH'
    action: str            # 'call' or 'put'
    candle_idx: int
    quality: str           # 'high', 'medium', 'soft'
    description: str
    is_solid: bool = True  # True = structural trigger, False = soft observation


@dataclass
class TrendLine:
    """A simple trendline defined by 2+ touch points."""
    slope: float
    intercept: float       # value at index 0
    touches: List[int]     # candle indices of touches
    line_type: str         # 'support' or 'resistance'
    tolerance: float = 0.0

    def value_at(self, idx: int) -> float:
        return self.intercept + self.slope * idx


class PatternDetector:
    """Pure price-action pattern detector — no indicators."""

    def __init__(
        self,
        exhaustion_body_ratio: float = 0.25,
        exhaustion_range_mult: float = 1.3,
        exhaustion_lookback: int = 5,
        engulfing_min_body_ratio: float = 0.50,
        spinning_top_max_body: float = 0.30,
        trendline_tolerance_pct: float = 0.15,
    ):
        self.exhaustion_body_ratio = exhaustion_body_ratio
        self.exhaustion_range_mult = exhaustion_range_mult
        self.exhaustion_lookback = exhaustion_lookback
        self.engulfing_min_body_ratio = engulfing_min_body_ratio
        self.spinning_top_max_body = spinning_top_max_body
        self.trendline_tolerance_pct = trendline_tolerance_pct

    # ───────────────────────────────────────────
    # 1. Exhaustion Candle
    # ───────────────────────────────────────────
    def detect_exhaustion(self, candles: List[Candle], run_length: int = 0) -> Optional[PatternSignal]:
        """
        Long wick, tiny body opposite the trend, bigger range than recent candles.
        Quality: HIGH at trend extremes (run_length >= 3).
        """
        if len(candles) < self.exhaustion_lookback + 1:
            return None

        current = candles[-1]
        if current.total_range <= 0:
            return None

        # Body must be tiny relative to range
        if current.body_ratio > self.exhaustion_body_ratio:
            return None

        # Range must be bigger than recent average
        recent_ranges = [c.total_range for c in candles[-(self.exhaustion_lookback + 1):-1]]
        avg_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else 0
        if avg_range <= 0 or current.total_range < avg_range * self.exhaustion_range_mult:
            return None

        # Determine direction based on wick dominance
        if current.upper_wick > current.lower_wick * 1.5:
            # Big upper wick = bearish exhaustion (reversal down)
            action = 'put'
            desc = (
                f"Exhaustion Candle (bearish) | Body={current.body_ratio*100:.0f}% | "
                f"Range={current.total_range:.5f} vs Avg={avg_range:.5f} | Upper Wick dominant"
            )
        elif current.lower_wick > current.upper_wick * 1.5:
            # Big lower wick = bullish exhaustion (reversal up)
            action = 'call'
            desc = (
                f"Exhaustion Candle (bullish) | Body={current.body_ratio*100:.0f}% | "
                f"Range={current.total_range:.5f} vs Avg={avg_range:.5f} | Lower Wick dominant"
            )
        else:
            return None

        quality = 'high' if run_length >= 3 else 'medium'
        return PatternSignal(
            pattern='EXHAUSTION',
            action=action,
            candle_idx=len(candles) - 1,
            quality=quality,
            description=desc,
            is_solid=True
        )

    # ───────────────────────────────────────────
    # 2. Engulfing Pattern
    # ───────────────────────────────────────────
    def detect_engulfing(self, candles: List[Candle]) -> Optional[PatternSignal]:
        """
        Current body fully swallows prior body.
        Quality: HIGH at S/R (checked externally via confluence scorer).
        """
        if len(candles) < 2:
            return None

        current = candles[-1]
        prev = candles[-2]

        if current.total_range <= 0 or prev.total_range <= 0:
            return None

        # Current body must be substantial
        if current.body_ratio < self.engulfing_min_body_ratio:
            return None

        curr_body_top = max(current.open, current.close)
        curr_body_bot = min(current.open, current.close)
        prev_body_top = max(prev.open, prev.close)
        prev_body_bot = min(prev.open, prev.close)

        # Current body must fully contain prior body
        if curr_body_top <= prev_body_top or curr_body_bot >= prev_body_bot:
            return None

        # Must be opposite color
        if current.is_bullish and prev.is_bullish:
            return None
        if current.is_bearish and prev.is_bearish:
            return None

        if current.is_bullish:
            action = 'call'
            desc = f"Bullish Engulfing | Body swallows prior ({curr_body_bot:.5f}-{curr_body_top:.5f} > {prev_body_bot:.5f}-{prev_body_top:.5f})"
        else:
            action = 'put'
            desc = f"Bearish Engulfing | Body swallows prior ({curr_body_bot:.5f}-{curr_body_top:.5f} > {prev_body_bot:.5f}-{prev_body_top:.5f})"

        return PatternSignal(
            pattern='ENGULFING',
            action=action,
            candle_idx=len(candles) - 1,
            quality='high',
            description=desc,
            is_solid=True
        )

    # ───────────────────────────────────────────
    # 3. Spinning Top
    # ───────────────────────────────────────────
    def detect_spinning_top(self, candles: List[Candle]) -> Optional[PatternSignal]:
        """
        Small body, wicks both sides — expect pause / continuation risk.
        Quality: MEDIUM (soft observation, not a trade trigger alone).
        """
        if len(candles) < 1:
            return None

        current = candles[-1]
        if current.total_range <= 0:
            return None

        if current.body_ratio > self.spinning_top_max_body:
            return None

        # Both wicks must be present (not just one-sided like a hammer)
        if current.upper_wick <= 0 or current.lower_wick <= 0:
            return None

        # Wicks should be roughly balanced (neither > 3x the other)
        wick_ratio = max(current.upper_wick, current.lower_wick) / min(current.upper_wick, current.lower_wick)
        if wick_ratio > 3.0:
            return None  # Too lopsided — more like a hammer/shooting star

        # Spinning tops are soft observations, not directional triggers
        return PatternSignal(
            pattern='SPINNING_TOP',
            action='neutral',
            candle_idx=len(candles) - 1,
            quality='medium',
            description=f"Spinning Top | Body={current.body_ratio*100:.0f}% | Wicks balanced (ratio={wick_ratio:.1f}x) — expect pause",
            is_solid=False  # Soft — never counts toward minimum confirmations
        )

    # ───────────────────────────────────────────
    # 4. Third Touch Breakout (Trendlines)
    # ───────────────────────────────────────────
    def find_trendlines(self, candles: List[Candle], min_touches: int = 2) -> List[TrendLine]:
        """
        Find support and resistance trendlines from swing points.
        Uses simple linear regression between pairs of swing lows/highs.
        """
        from .swing_detector import SwingDetector
        detector = SwingDetector(left_bars=2, right_bars=2)
        swings = detector.find_swings(candles)

        lines: List[TrendLine] = []
        n = len(candles)
        tol_abs = (candles[-1].close * self.trendline_tolerance_pct / 100.0) if candles else 0

        # Build support trendlines from swing lows
        swing_lows = [s for s in swings if s.is_low]
        for i in range(len(swing_lows)):
            for j in range(i + 1, len(swing_lows)):
                s1, s2 = swing_lows[i], swing_lows[j]
                if s1.index == s2.index:
                    continue
                slope = (s2.price - s1.price) / (s2.index - s1.index)
                intercept = s1.price - slope * s1.index

                # Count touches
                touches = []
                for k, c in enumerate(candles):
                    line_val = intercept + slope * k
                    if abs(c.low - line_val) <= tol_abs:
                        touches.append(k)

                if len(touches) >= min_touches:
                    lines.append(TrendLine(
                        slope=slope, intercept=intercept,
                        touches=touches, line_type='support',
                        tolerance=tol_abs
                    ))

        # Build resistance trendlines from swing highs
        swing_highs = [s for s in swings if s.is_high]
        for i in range(len(swing_highs)):
            for j in range(i + 1, len(swing_highs)):
                s1, s2 = swing_highs[i], swing_highs[j]
                if s1.index == s2.index:
                    continue
                slope = (s2.price - s1.price) / (s2.index - s1.index)
                intercept = s1.price - slope * s1.index

                touches = []
                for k, c in enumerate(candles):
                    line_val = intercept + slope * k
                    if abs(c.high - line_val) <= tol_abs:
                        touches.append(k)

                if len(touches) >= min_touches:
                    lines.append(TrendLine(
                        slope=slope, intercept=intercept,
                        touches=touches, line_type='resistance',
                        tolerance=tol_abs
                    ))

        return lines

    def detect_third_touch(self, candles: List[Candle]) -> Optional[PatternSignal]:
        """
        Trendline with 2 prior touches, 3rd touch at current candle is the trigger.
        Quality: HIGH with OB/FVG backup (checked externally).
        """
        if len(candles) < 10:
            return None

        lines = self.find_trendlines(candles, min_touches=2)
        current = candles[-1]
        current_idx = len(candles) - 1

        for line in lines:
            # Only care about lines with exactly 2 prior touches (we're looking for the 3rd)
            prior_touches = [t for t in line.touches if t < current_idx]
            if len(prior_touches) < 2:
                continue

            line_val = line.value_at(current_idx)

            if line.line_type == 'support':
                if abs(current.low - line_val) <= line.tolerance:
                    return PatternSignal(
                        pattern='THIRD_TOUCH',
                        action='call',
                        candle_idx=current_idx,
                        quality='high',
                        description=f"3rd Touch Support TL (slope={line.slope:.6f}) | Touches: {len(prior_touches)+1} | Level={line_val:.5f}",
                        is_solid=True
                    )
            elif line.line_type == 'resistance':
                if abs(current.high - line_val) <= line.tolerance:
                    return PatternSignal(
                        pattern='THIRD_TOUCH',
                        action='put',
                        candle_idx=current_idx,
                        quality='high',
                        description=f"3rd Touch Resistance TL (slope={line.slope:.6f}) | Touches: {len(prior_touches)+1} | Level={line_val:.5f}",
                        is_solid=True
                    )

        return None

    # ───────────────────────────────────────────
    # Combined scan
    # ───────────────────────────────────────────
    def scan_all(self, candles: List[Candle], run_length: int = 0) -> List[PatternSignal]:
        """Run all pattern detectors and return all matches."""
        results = []
        for detect_fn in [
            lambda: self.detect_exhaustion(candles, run_length),
            lambda: self.detect_engulfing(candles),
            lambda: self.detect_spinning_top(candles),
            lambda: self.detect_third_touch(candles),
        ]:
            sig = detect_fn()
            if sig:
                results.append(sig)
        return results
