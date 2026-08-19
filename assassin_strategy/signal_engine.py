"""
Assassin Strategy Signal Engine
===============================
Combines Doji breakouts, Quasimodo (QM) structure, Fair Value Gaps (FVG),
and Margin of Safety retests into high-probability binary options signals.
"""
from dataclasses import dataclass
from typing import List, Optional, Dict, Tuple
import time

from .candle_utils import Candle, detect_gap
from .doji_detector import DojiDetector, DojiRangeBox
from .fvg_detector import FVGDetector, FVG
from .qm_pattern import QMPatternDetector, QMPattern
from .safety_zone import MarginOfSafetyFilter, PendingSetup


@dataclass
class AssassinSignal:
    symbol: str
    action: str            # 'call' or 'put'
    price: float
    confidence: float      # e.g. 0.85 to 0.95
    trigger: str           # Detailed description of confluence
    pattern_type: str      # 'QM_CONFLUENCE' or 'DOJI_BREAKOUT'
    expiry_seconds: int    # Target expiry for trade (e.g. 60s to 300s)
    timestamp: float
    metadata: Dict = None


class AssassinSignalEngine:
    def __init__(
        self,
        doji_threshold: float = 0.10,
        fvg_min_pct: float = 0.01,
        swing_left: int = 2,
        swing_right: int = 2,
        safety_tolerance_pct: float = 0.08,
        default_expiry_seconds: int = 300,
        require_safety_retest: bool = True
    ):
        self.doji_detector = DojiDetector(body_threshold=doji_threshold)
        self.fvg_detector = FVGDetector(min_gap_pct=fvg_min_pct)
        self.qm_detector = QMPatternDetector(swing_left=swing_left, swing_right=swing_right)
        self.safety_filter = MarginOfSafetyFilter(tolerance_pct=safety_tolerance_pct)
        
        self.default_expiry = default_expiry_seconds
        self.require_safety_retest = require_safety_retest
        
        # History per symbol: {symbol: list of Candle}
        self.candle_history: Dict[str, List[Candle]] = {}
        self.last_signals: Dict[str, float] = {}

    def update_candle(self, symbol: str, candle: Candle) -> List[AssassinSignal]:
        """
        Feed a newly completed candle into the engine and evaluate all confluence layers.
        
        Returns:
            List of confirmed AssassinSignal objects ready for trade dispatch.
        """
        if symbol not in self.candle_history:
            self.candle_history[symbol] = []

        history = self.candle_history[symbol]
        prev_candle = history[-1] if history else None
        history.append(candle)
        current_idx = len(history) - 1

        signals: List[AssassinSignal] = []

        # 1. Check if any existing armed Pending Setups have reached safety zone
        triggered_setups = self.safety_filter.check_pending(symbol, candle.close, current_idx)
        for setup in triggered_setups:
            sig = AssassinSignal(
                symbol=symbol,
                action=setup.action,
                price=candle.close,
                confidence=0.92,
                trigger=f"{setup.trigger_source} | Safety Retest Confirmed at {setup.target_safety_level:.2f}",
                pattern_type='SAFETY_RETEST_TRIGGER',
                expiry_seconds=self.default_expiry,
                timestamp=candle.timestamp,
                metadata={'setup_id': setup.setup_id}
            )
            signals.append(sig)

        # 2. Update Doji Detector & Check Doji Breakouts
        doji_breakouts = self.doji_detector.process_candle(symbol, candle, prev_candle, current_idx)
        for box, action, trig_desc in doji_breakouts:
            # Check Round Number Margin of Safety
            step = MarginOfSafetyFilter.get_round_number_step(candle.close)
            lower_rn, upper_rn = MarginOfSafetyFilter.find_nearest_round_numbers(candle.close, step)
            safety_target = lower_rn if action == 'call' else upper_rn

            if self.require_safety_retest:
                # Arm pending setup for retest of the Doji boundary or Round Number
                target_retest = box.high if action == 'call' else box.low
                self.safety_filter.arm_setup(
                    setup_id=f"DOJI_{symbol}_{current_idx}",
                    symbol=symbol,
                    action=action,
                    current_price=candle.close,
                    safety_level=target_retest,
                    trigger_source=trig_desc,
                    timestamp=candle.timestamp,
                    candle_idx=current_idx
                )
            else:
                # Instant execution on confirmed breakout
                sig = AssassinSignal(
                    symbol=symbol,
                    action=action,
                    price=candle.close,
                    confidence=0.88,
                    trigger=f"{trig_desc} (RN={safety_target:.2f})",
                    pattern_type='DOJI_BREAKOUT',
                    expiry_seconds=self.default_expiry,
                    timestamp=candle.timestamp,
                    metadata={'doji_box': box}
                )
                signals.append(sig)

        # 3. Detect Active Fair Value Gaps (FVG) on rolling lookback
        lookback_slice = history[-100:] if len(history) > 100 else history
        active_fvgs = self.fvg_detector.scan_fvgs(lookback_slice)

        # 4. Detect Quasimodo (QM) Patterns + Order Block + FVG Overlap
        qm_patterns = self.qm_detector.detect_qm(lookback_slice, active_fvgs)
        for qm in qm_patterns:
            action = 'call' if qm.pattern_type == 'bullish' else 'put'
            fvg_note = f" + FVG Overlap [{qm.fvg_confluence.zone_low:.2f}-{qm.fvg_confluence.zone_high:.2f}]" if qm.fvg_confluence else ""
            
            # The high-probability reversal entry is at the QM Level / Order Block
            safety_target = qm.qm_level

            if self.require_safety_retest:
                self.safety_filter.arm_setup(
                    setup_id=f"QM_{symbol}_{current_idx}",
                    symbol=symbol,
                    action=action,
                    current_price=candle.close,
                    safety_level=safety_target,
                    trigger_source=f"QM {qm.pattern_type.upper()}{fvg_note} Level={qm.qm_level:.2f}",
                    timestamp=candle.timestamp,
                    candle_idx=current_idx
                )
            else:
                sig = AssassinSignal(
                    symbol=symbol,
                    action=action,
                    price=candle.close,
                    confidence=0.94 if qm.fvg_confluence else 0.89,
                    trigger=f"QM {qm.pattern_type.upper()}{fvg_note} Retest={qm.qm_level:.2f}",
                    pattern_type='QM_CONFLUENCE',
                    expiry_seconds=self.default_expiry,
                    timestamp=candle.timestamp,
                    metadata={'qm_pattern': qm}
                )
                signals.append(sig)

        return signals
