"""
Assassin Strategy Signal Engine v2
===================================
Full Price-Action Confluence Engine implementing the Assassin Analyzer rules:

  Step 1 — Read Market Regime (trending vs ranging gates pattern validity)
  Step 2 — Identify Structure (OB, FVG, S/R, Round Numbers, Trendlines)
  Step 3 — Scan Signal Patterns (Exhaustion, Engulfing, Doji, QM, Third Touch)
  Step 4 — Count Confirmations (Solid vs Soft, genuinely independent)
  Step 5 — Apply Hard Rules (Contact not proximity, second-candle, post-run caution)
  Step 6 — Deliver Verdict (Take It / Lean / Leave It)
"""
from dataclasses import dataclass
from typing import List, Optional, Dict
import os
import time
import logging

from .candle_utils import Candle, detect_gap
from .doji_detector import DojiDetector, DojiRangeBox
from .fvg_detector import FVGDetector, FVG
from .qm_pattern import QMPatternDetector, QMPattern
from .safety_zone import MarginOfSafetyFilter, PendingSetup
from .pattern_detector import PatternDetector, PatternSignal
from .sr_levels import SRDetector, SRLevel
from .regime_detector import RegimeDetector, MarketRegime, MarketState
from .confluence_scorer import ConfluenceScorer, Confirmation, ConfluenceVerdict

logger = logging.getLogger(__name__)


@dataclass
class AssassinSignal:
    symbol: str
    action: str            # 'call' or 'put'
    price: float
    confidence: float      # 0.75 to 0.96
    trigger: str           # Detailed description of confluence
    pattern_type: str      # 'TAKE_IT', 'LEAN', etc.
    expiry_seconds: int
    timestamp: float
    verdict: str = ''      # 'TAKE_IT' or 'LEAN'
    regime: str = ''       # 'TRENDING_UP', 'TRENDING_DOWN', 'RANGING'
    solid_count: int = 0
    soft_count: int = 0
    metadata: Dict = None


class AssassinSignalEngine:
    """
    Full price-action confluence engine.
    No RSI, no MACD, no Bollinger — raw structure only.
    """

    def __init__(
        self,
        doji_threshold: float = 0.10,
        fvg_min_pct: float = 0.01,
        swing_left: int = 2,
        swing_right: int = 2,
        safety_tolerance_pct: float = 0.08,
        default_expiry_seconds: int = 300,
        require_safety_retest: bool = True,
    ):
        # ─── Core Detectors ───
        self.doji_detector = DojiDetector(body_threshold=doji_threshold)
        self.fvg_detector = FVGDetector(min_gap_pct=fvg_min_pct)
        self.qm_detector = QMPatternDetector(swing_left=swing_left, swing_right=swing_right)
        self.safety_filter = MarginOfSafetyFilter(tolerance_pct=safety_tolerance_pct)

        # ─── New Price-Action Modules ───
        self.pattern_detector = PatternDetector()
        self.sr_detector = SRDetector()
        self.regime_detector = RegimeDetector()
        self.confluence_scorer = ConfluenceScorer()

        self.default_expiry = default_expiry_seconds
        self.require_safety_retest = require_safety_retest
        self.min_confidence = float(os.environ.get("MIN_CONFIDENCE", "0.75"))  # 75% = all 2+ solid LEAN setups (proven 24-win config)

        # Per-symbol candle history
        self.candle_history: Dict[str, List[Candle]] = {}
        self.last_signals: Dict[str, float] = {}
        self.signal_cooldown = 120.0  # 2min cooldown per symbol (prevents 10+ trades on same asset in 15min)

    def update_candle(self, symbol: str, candle: Candle) -> List[AssassinSignal]:
        """
        Feed a newly completed candle into the engine.
        Executes the full 6-step analysis pipeline.
        
        Returns:
            List of confirmed AssassinSignal objects ready for trade dispatch.
        """
        if symbol not in self.candle_history:
            self.candle_history[symbol] = []

        history = self.candle_history[symbol]
        prev_candle = history[-1] if history else None
        history.append(candle)
        current_idx = len(history) - 1

        # Don't generate signals until we have enough data (seeded on boot)
        if len(history) < 10:
            return []

        # Cooldown check
        now = time.time()
        if symbol in self.last_signals:
            if now - self.last_signals[symbol] < self.signal_cooldown:
                return []

        signals: List[AssassinSignal] = []

        # ═══════════════════════════════════════════════
        # STEP 1: READ MARKET REGIME
        # ═══════════════════════════════════════════════
        regime = self.regime_detector.update(symbol, candle, history)
        state = self.regime_detector.get_state(symbol)

        # ═══════════════════════════════════════════════
        # STEP 2: IDENTIFY STRUCTURE
        # ═══════════════════════════════════════════════
        lookback_slice = history[-100:] if len(history) > 100 else history

        # 2a. Fair Value Gaps
        active_fvgs = self.fvg_detector.scan_fvgs(lookback_slice)

        # 2b. Support/Resistance Levels
        sr_levels = self.sr_detector.detect_levels(lookback_slice)
        round_numbers = SRDetector.find_round_numbers(candle.close)

        # 2c. Check if price is touching any key level RIGHT NOW
        at_sr, touching_sr = self.sr_detector.is_at_key_level(candle.close, lookback_slice)

        # 2d. Check FVG fill contact
        fvg_contact = None
        for fvg in active_fvgs:
            if fvg.is_price_inside(candle.close):
                fvg_contact = fvg
                break

        # 2e. Quasimodo patterns with Order Block + FVG overlap
        qm_patterns = self.qm_detector.detect_qm(lookback_slice, active_fvgs)

        # ═══════════════════════════════════════════════
        # STEP 3: SCAN FOR SIGNAL PATTERNS
        # ═══════════════════════════════════════════════
        confirmations: List[Confirmation] = []

        # 3a. Candlestick Patterns (Exhaustion, Engulfing, Spinning Top, Third Touch)
        pa_signals = self.pattern_detector.scan_all(history, run_length=state.run_length)
        for pa in pa_signals:
            # Regime gate: Doji breakouts work in ranges, Exhaustion at trend extremes
            if pa.pattern == 'EXHAUSTION':
                if regime.regime in ('TRENDING_UP', 'TRENDING_DOWN'):
                    pa.quality = 'high'
                else:
                    pa.quality = 'medium'
            elif pa.pattern == 'ENGULFING':
                if at_sr:
                    pa.quality = 'high'
                else:
                    pa.quality = 'medium'

            confirmations.append(Confirmation(
                source=pa.pattern,
                is_solid=pa.is_solid,
                action=pa.action if pa.action != 'neutral' else 'call',
                description=pa.description,
                category=f'pattern_{pa.pattern}'
            ))

        # 3b. Doji Breakouts
        doji_breakouts = self.doji_detector.process_candle(symbol, candle, prev_candle, current_idx)
        for box, action, trig_desc in doji_breakouts:
            # Regime gate: Doji works best in ranging markets
            quality_boost = regime.regime == 'RANGING'
            confirmations.append(Confirmation(
                source='DOJI_BREAKOUT',
                is_solid=True,
                action=action,
                description=f"{trig_desc} {'(Ranging market = ideal)' if quality_boost else ''}",
                category='pattern_DOJI'
            ))

        # 3c. Quasimodo Patterns
        for qm in qm_patterns:
            action = 'call' if qm.pattern_type == 'bullish' else 'put'
            fvg_note = f" + FVG Overlap" if qm.fvg_confluence else ""
            confirmations.append(Confirmation(
                source='QM_PATTERN',
                is_solid=True,
                action=action,
                description=f"QM {qm.pattern_type.upper()}{fvg_note} Level={qm.qm_level:.5f}",
                category='structure_QM'
            ))

        # ═══════════════════════════════════════════════
        # STEP 4: COUNT STRUCTURAL CONFIRMATIONS
        # ═══════════════════════════════════════════════

        # 4a. S/R Contact (SOLID — only if actually touching, not "approaching")
        if at_sr and touching_sr:
            sr_action = 'call' if touching_sr.level_type == 'support' else 'put'
            confirmations.append(Confirmation(
                source='SR_CONTACT',
                is_solid=True,
                action=sr_action,
                description=f"{touching_sr.level_type.upper()} contact at {touching_sr.price:.5f} ({touching_sr.touches} touches, {touching_sr.strength})",
                category='price_level'
            ))

        # 4b. Round Number Contact (SOLID)
        for rn in round_numbers:
            if rn.is_price_at_level(candle.close, 0.05):
                confirmations.append(Confirmation(
                    source='ROUND_NUMBER',
                    is_solid=True,
                    action='neutral',  # Direction comes from other patterns
                    description=f"Round Number contact at {rn.price:.5f}",
                    category='price_level_rn'
                ))
                break  # Only count one RN

        # 4c. FVG Fill Contact (SOLID — price drawn back to fill the gap)
        if fvg_contact:
            fvg_action = 'call' if fvg_contact.fvg_type == 'bullish' else 'put'
            confirmations.append(Confirmation(
                source='FVG_FILL',
                is_solid=True,
                action=fvg_action,
                description=f"FVG {fvg_contact.fvg_type} fill at [{fvg_contact.zone_low:.5f}-{fvg_contact.zone_high:.5f}]",
                category='structure_FVG'
            ))

        # 4d. Order Block Contact (SOLID — checked via QM patterns)
        for qm in qm_patterns:
            ob = qm.order_block
            if ob.zone_low <= candle.close <= ob.zone_high:
                ob_action = 'call' if ob.ob_type == 'bullish' else 'put'
                confirmations.append(Confirmation(
                    source='OB_CONTACT',
                    is_solid=True,
                    action=ob_action,
                    description=f"Order Block {ob.ob_type} contact [{ob.zone_low:.5f}-{ob.zone_high:.5f}]",
                    category='structure_OB'
                ))

        # 4e. Post-Run Caution (SOFT — not a directional signal, but modifies confidence)
        if state.post_run_caution:
            reversal_action = 'put' if state.run_color == 'green' else 'call'
            confirmations.append(Confirmation(
                source='POST_RUN_CAUTION',
                is_solid=False,
                action=reversal_action,
                description=f"Post-run caution: {state.run_length} consecutive {state.run_color} candles — lean reversal",
                category='regime_caution'
            ))

        # 4f. Regime Direction (SOFT — narrative context, never counts toward minimum)
        if regime.regime in ('TRENDING_UP', 'TRENDING_DOWN'):
            trend_action = 'call' if regime.regime == 'TRENDING_UP' else 'put'
            confirmations.append(Confirmation(
                source='REGIME_TREND',
                is_solid=False,
                action=trend_action,
                description=f"Macro regime: {regime.description}",
                category='regime_trend'
            ))

        # ═══════════════════════════════════════════════
        # STEP 5: APPLY HARD RULES
        # ═══════════════════════════════════════════════

        # Rule 1: Contact, not proximity — already enforced in detection logic
        # Rule 2: Second-candle rule — verify follow-through
        confirmations = self._apply_second_candle_rule(confirmations, candle, prev_candle)

        # ═══════════════════════════════════════════════
        # STEP 6: DELIVER VERDICT
        # ═══════════════════════════════════════════════
        verdict = self.confluence_scorer.score(
            confirmations,
            post_run_caution=state.post_run_caution
        )

        # ═══════════════════════════════════════════════
        # STEP 7: TREND ALIGNMENT GATE
        # ═══════════════════════════════════════════════
        # Forensic data: ALL 15 losses on Aug 22 were CALLs in TRENDING_DOWN without reversal proof.
        # Rule: In trending regimes, only trade WITH the trend UNLESS Engulfing or QM proves reversal.
        has_reversal_proof = any(
            c.source in ('ENGULFING', 'QM_PATTERN', 'EXHAUSTION') and c.action == verdict.action
            for c in verdict.confirmations
        )

        is_counter_trend = False
        if regime.regime == 'TRENDING_DOWN' and verdict.action == 'call' and not has_reversal_proof:
            is_counter_trend = True
        elif regime.regime == 'TRENDING_UP' and verdict.action == 'put' and not has_reversal_proof:
            is_counter_trend = True

        if is_counter_trend and verdict.verdict in ('TAKE_IT', 'LEAN'):
            logger.info(
                f"🛡️ [TREND GATE] [{symbol}] {verdict.action.upper()} blocked — "
                f"Counter-trend in {regime.regime} without Engulfing/QM reversal proof. "
                f"Confidence was {verdict.confidence*100:.0f}%."
            )
        # 75% Filter: Trades all verified 2+ solid setups (TAKE_IT and LEAN)
        elif verdict.verdict in ('TAKE_IT', 'LEAN') and verdict.confidence >= self.min_confidence and verdict.action in ('call', 'put'):
            sig = AssassinSignal(
                symbol=symbol,
                action=verdict.action,
                price=candle.close,
                confidence=verdict.confidence,
                trigger=verdict.reasoning,
                pattern_type=verdict.verdict,
                expiry_seconds=self.default_expiry,
                timestamp=candle.timestamp,
                verdict=verdict.verdict,
                regime=regime.regime,
                solid_count=verdict.solid_count,
                soft_count=verdict.soft_count,
                metadata={
                    'confirmations': [c.description for c in verdict.confirmations],
                    'regime': regime.regime,
                    'run_length': state.run_length,
                    'run_color': state.run_color,
                }
            )

            # Log the trade signal
            verdict_tag = "🔥 [TAKE_IT]" if verdict.verdict == "TAKE_IT" else "📊 [LEAN]"
            logger.info(
                f"{verdict_tag} [{symbol}] {verdict.action.upper()} | "
                f"Solid={verdict.solid_count} Soft={verdict.soft_count} | "
                f"Confidence={verdict.confidence*100:.0f}% | "
                f"Regime={regime.regime} Run={state.run_length}{state.run_color[0].upper()}"
            )
            for c in verdict.confirmations:
                logger.info(f"  {'■' if c.is_solid else '□'} [{c.source}] {c.description}")

            signals.append(sig)
            self.last_signals[symbol] = now
        elif verdict.verdict == 'LEAVE_IT' or verdict.confidence < self.min_confidence:
            logger.info(
                f"⏭️ [SKIP] [{symbol}] {verdict.action.upper()} ({verdict.confidence*100:.0f}%) — {verdict.reasoning}"
            )

        # Also check pending safety retests (from prior armed setups)
        triggered_setups = self.safety_filter.check_pending(symbol, candle.close, current_idx)
        for setup in triggered_setups:
            sig = AssassinSignal(
                symbol=symbol,
                action=setup.action,
                price=candle.close,
                confidence=0.92,
                trigger=f"{setup.trigger_source} | Safety Retest Confirmed at {setup.target_safety_level:.5f}",
                pattern_type='SAFETY_RETEST',
                expiry_seconds=self.default_expiry,
                timestamp=candle.timestamp,
                verdict='TAKE_IT',
                regime=regime.regime,
                metadata={'setup_id': setup.setup_id}
            )
            signals.append(sig)
            self.last_signals[symbol] = now

        return signals

    def _apply_second_candle_rule(
        self, confirmations: List[Confirmation],
        current: Candle, prev: Optional[Candle]
    ) -> List[Confirmation]:
        """
        Hard Rule #2: One bounce candle is not enough — need follow-through.
        If the only evidence is a single candle pattern with no structural backup,
        downgrade solid to soft.
        """
        if prev is None:
            return confirmations

        # Count purely pattern-based solids
        pattern_solids = [c for c in confirmations if c.is_solid and c.source in (
            'EXHAUSTION', 'ENGULFING', 'SPINNING_TOP'
        )]
        structure_solids = [c for c in confirmations if c.is_solid and c.source in (
            'SR_CONTACT', 'FVG_FILL', 'OB_CONTACT', 'QM_PATTERN', 'DOJI_BREAKOUT',
            'THIRD_TOUCH', 'ROUND_NUMBER'
        )]

        # If we have pattern signals but NO structural support, check follow-through
        if pattern_solids and not structure_solids:
            # Verify follow-through: current candle must agree with previous candle direction
            if current.is_bullish and prev.is_bearish:
                # Bullish reversal — check that current close > prev high (follow-through)
                if current.close <= prev.high:
                    for c in pattern_solids:
                        c.is_solid = False
                        c.description += " [downgraded: no follow-through]"
            elif current.is_bearish and prev.is_bullish:
                if current.close >= prev.low:
                    for c in pattern_solids:
                        c.is_solid = False
                        c.description += " [downgraded: no follow-through]"

        return confirmations
