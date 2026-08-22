"""
Market Regime & Running State Detection Module
===============================================
Determines whether the market is trending or ranging (gates which patterns are valid),
and tracks running state across candles (run length, last swing, active zones).
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from .candle_utils import Candle


@dataclass
class MarketRegime:
    regime: str             # 'TRENDING_UP', 'TRENDING_DOWN', 'RANGING', 'UNKNOWN'
    strength: float         # 0.0 (no trend) to 1.0 (strong trend)
    run_length: int         # Consecutive same-color candles
    run_color: str          # 'green', 'red', or 'mixed'
    last_swing_high: float
    last_swing_low: float
    description: str


@dataclass
class MarketState:
    """Running state tracked across every candle for each symbol."""
    run_length: int = 0
    run_color: str = 'none'
    last_swing_high: float = 0.0
    last_swing_low: float = float('inf')
    regime: str = 'UNKNOWN'
    regime_strength: float = 0.0
    prior_signals: List[str] = field(default_factory=list)
    prior_results: List[str] = field(default_factory=list)  # 'win', 'loss', 'skip'
    post_run_caution: bool = False  # True after 3+ same-color candles


class RegimeDetector:
    """
    Market regime detection using pure price action:
    - Higher Highs + Higher Lows = TRENDING_UP
    - Lower Highs + Lower Lows = TRENDING_DOWN
    - Otherwise = RANGING
    """

    def __init__(self, lookback: int = 20, min_trend_swings: int = 3):
        self.lookback = lookback
        self.min_trend_swings = min_trend_swings
        # Per-symbol running state
        self.states: Dict[str, MarketState] = {}

    def _get_state(self, symbol: str) -> MarketState:
        if symbol not in self.states:
            self.states[symbol] = MarketState()
        return self.states[symbol]

    def update(self, symbol: str, candle: Candle, candles: List[Candle]) -> MarketRegime:
        """
        Update running state and classify market regime for a symbol.
        Called on every candle close.
        """
        state = self._get_state(symbol)

        # 1. Track Run Length (consecutive same-color candles)
        if candle.is_bullish:
            if state.run_color == 'green':
                state.run_length += 1
            else:
                state.run_color = 'green'
                state.run_length = 1
        elif candle.is_bearish:
            if state.run_color == 'red':
                state.run_length += 1
            else:
                state.run_color = 'red'
                state.run_length = 1
        else:
            state.run_color = 'flat'
            state.run_length = 0

        # Post-run caution: after 3+ same-color candles, next candle leans toward relief/reversal
        state.post_run_caution = state.run_length >= 3

        # 2. Track Swing Highs/Lows from recent candles
        recent = candles[-min(self.lookback, len(candles)):]
        if recent:
            state.last_swing_high = max(c.high for c in recent)
            state.last_swing_low = min(c.low for c in recent)

        # 3. Classify Regime via Higher Highs/Higher Lows or Lower Highs/Lower Lows
        regime, strength, description = self._classify_regime(recent)
        state.regime = regime
        state.regime_strength = strength

        return MarketRegime(
            regime=regime,
            strength=strength,
            run_length=state.run_length,
            run_color=state.run_color,
            last_swing_high=state.last_swing_high,
            last_swing_low=state.last_swing_low,
            description=description
        )

    def _classify_regime(self, candles: List[Candle]):
        """
        Classify regime using swing structure:
        - HH + HL = Uptrend
        - LH + LL = Downtrend
        - Mixed = Ranging
        """
        if len(candles) < 8:
            return 'UNKNOWN', 0.0, 'Insufficient data'

        from .swing_detector import SwingDetector
        detector = SwingDetector(left_bars=2, right_bars=2)
        swings = detector.find_swings(candles)

        if len(swings) < self.min_trend_swings:
            return 'RANGING', 0.3, f'Only {len(swings)} swings detected — choppy/ranging'

        # Extract swing highs and lows separately
        highs = [s.price for s in swings if s.is_high]
        lows = [s.price for s in swings if s.is_low]

        hh_count = 0
        lh_count = 0
        for i in range(1, len(highs)):
            if highs[i] > highs[i - 1]:
                hh_count += 1
            elif highs[i] < highs[i - 1]:
                lh_count += 1

        hl_count = 0
        ll_count = 0
        for i in range(1, len(lows)):
            if lows[i] > lows[i - 1]:
                hl_count += 1
            elif lows[i] < lows[i - 1]:
                ll_count += 1

        total_moves = max(hh_count + lh_count + hl_count + ll_count, 1)

        # Uptrend: majority higher highs AND higher lows
        up_score = (hh_count + hl_count) / total_moves
        down_score = (lh_count + ll_count) / total_moves

        if up_score >= 0.65:
            strength = min(up_score, 1.0)
            return 'TRENDING_UP', strength, f'Uptrend: {hh_count}HH + {hl_count}HL (score={up_score:.0%})'
        elif down_score >= 0.65:
            strength = min(down_score, 1.0)
            return 'TRENDING_DOWN', strength, f'Downtrend: {lh_count}LH + {ll_count}LL (score={down_score:.0%})'
        else:
            return 'RANGING', 0.4, f'Ranging: up={up_score:.0%} down={down_score:.0%} — no clear direction'

    def get_state(self, symbol: str) -> MarketState:
        """Get the current running state for a symbol."""
        return self._get_state(symbol)
