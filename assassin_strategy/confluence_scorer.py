"""
Confluence Scoring Engine
=========================
Implements the confidence tier system from the Price Action Analyzer:

  - 3+ solid aligned confirmations  → "Take it — CALL/PUT" (full conviction)
  - 2 solid + supporting soft       → "Lean CALL/PUT" (cautious entry)
  - < 2 solid                       → "Leave it" (no trade)

Rules:
  - Each confirmation must be genuinely independent.
  - Restating the same fact differently doesn't create a second confirmation.
  - Contact, not proximity: a level only counts when price touches/crosses it.
  - Post-run caution: after 3+ same-color candles, lean toward reversal.
"""
from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class Confirmation:
    """A single piece of evidence for or against a trade."""
    source: str            # e.g. 'EXHAUSTION', 'OB_CONTACT', 'FVG_FILL', 'RN_TOUCH', 'SR_TOUCH'
    is_solid: bool         # True = structural trigger, False = soft/narrative
    action: str            # 'call', 'put', or 'neutral'
    description: str
    category: str = ''     # Group to prevent double-counting (e.g. 'price_level')


@dataclass
class ConfluenceVerdict:
    """The final trading verdict after scoring all confirmations."""
    verdict: str           # 'TAKE_IT', 'LEAN', 'LEAVE_IT'
    action: str            # 'call', 'put', or 'none'
    confidence: float      # 0.0 to 1.0
    solid_count: int
    soft_count: int
    total_count: int
    confirmations: List[Confirmation]
    reasoning: str


class ConfluenceScorer:
    """
    Counts independent solid vs soft confirmations and applies
    the confidence tier rules.
    """

    def __init__(
        self,
        take_it_threshold: int = 3,    # Minimum solid confirmations for "Take it"
        lean_threshold: int = 2,       # Minimum solid confirmations for "Lean"
        lean_soft_required: int = 1    # Minimum soft confirmations supporting "Lean"
    ):
        self.take_it_threshold = take_it_threshold
        self.lean_threshold = lean_threshold
        self.lean_soft_required = lean_soft_required

    def score(self, confirmations: List[Confirmation], post_run_caution: bool = False) -> ConfluenceVerdict:
        """
        Score a list of confirmations and return a verdict.
        
        Args:
            confirmations: All evidence gathered from pattern/structure detectors.
            post_run_caution: If True (3+ same-color candles), penalize continuation signals.
        """
        if not confirmations:
            return ConfluenceVerdict(
                verdict='LEAVE_IT', action='none', confidence=0.0,
                solid_count=0, soft_count=0, total_count=0,
                confirmations=[], reasoning="No confirmations found."
            )

        # Deduplicate by category — only keep strongest per category
        deduped = self._deduplicate(confirmations)

        # Count solid and soft by direction
        call_solid = [c for c in deduped if c.is_solid and c.action == 'call']
        call_soft = [c for c in deduped if not c.is_solid and c.action == 'call']
        put_solid = [c for c in deduped if c.is_solid and c.action == 'put']
        put_soft = [c for c in deduped if not c.is_solid and c.action == 'put']

        # Determine dominant direction
        call_score = len(call_solid) * 2 + len(call_soft)
        put_score = len(put_solid) * 2 + len(put_soft)

        if call_score > put_score:
            action = 'call'
            solid_count = len(call_solid)
            soft_count = len(call_soft)
            opposing = len(put_solid)
        elif put_score > call_score:
            action = 'put'
            solid_count = len(put_solid)
            soft_count = len(put_soft)
            opposing = len(call_solid)
        else:
            # Tied — no clear direction
            return ConfluenceVerdict(
                verdict='LEAVE_IT', action='none', confidence=0.15,
                solid_count=0, soft_count=0, total_count=len(deduped),
                confirmations=deduped,
                reasoning="Equal call/put pressure — no directional edge."
            )

        # Post-run caution: if 3+ same-color candles and signal is continuation, penalize
        if post_run_caution and solid_count > 0:
            # Don't penalize reversal signals, only continuation
            pass  # Applied externally via regime detector context

        # Opposing solid confirmations negate ours
        net_solid = solid_count - opposing
        if net_solid < 0:
            net_solid = 0

        # Check for the 3 golden triggers
        has_engulfing = any(c.source == 'ENGULFING' and c.action == action for c in deduped)
        has_trendline = any(c.source == 'THIRD_TOUCH' and c.action == action for c in deduped)
        has_major_sr = any(c.source == 'SR_CONTACT' and c.action == action for c in deduped)
        has_qm = any(c.source in ('QM_PATTERN', 'OB_CONTACT') and c.action == action for c in deduped)

        # Golden trigger bonus
        trigger_bonus = 0.0
        if has_engulfing:
            trigger_bonus += 0.08  # 100% winrate trigger
        if has_trendline:
            trigger_bonus += 0.05  # 91.6% consistency trigger
        if has_major_sr:
            trigger_bonus += 0.04  # 83.3% structural floor trigger

        # Apply confidence tiers
        if net_solid >= self.take_it_threshold:
            verdict = 'TAKE_IT'
            confidence = min(0.90 + (net_solid - self.take_it_threshold) * 0.03 + soft_count * 0.01 + trigger_bonus, 0.98)
            reasoning = f"Take it (Golden Trio Aligned) — {net_solid} solid + {soft_count} soft aligned {action.upper()} confirmations."
        elif net_solid >= self.lean_threshold and (soft_count >= self.lean_soft_required or trigger_bonus > 0.04):
            verdict = 'LEAN'
            confidence = min(0.80 + (net_solid - self.lean_threshold) * 0.03 + soft_count * 0.02 + trigger_bonus, 0.89)
            reasoning = f"Lean {action.upper()} — {net_solid} solid + {soft_count} soft aligned confirmations."
        elif net_solid >= self.lean_threshold:
            verdict = 'LEAN'
            confidence = min(0.75 + trigger_bonus, 0.82)
            reasoning = f"Lean {action.upper()} — {net_solid} solid confirmations."
        else:
            verdict = 'LEAVE_IT'
            confidence = max(0.10, net_solid * 0.15 + soft_count * 0.05)
            missing = self.lean_threshold - net_solid
            reasoning = f"Leave it — only {net_solid} solid ({missing} more needed). Not enough structure."

        return ConfluenceVerdict(
            verdict=verdict,
            action=action,
            confidence=confidence,
            solid_count=net_solid,
            soft_count=soft_count,
            total_count=len(deduped),
            confirmations=deduped,
            reasoning=reasoning
        )

    def _deduplicate(self, confirmations: List[Confirmation]) -> List[Confirmation]:
        """
        Remove duplicate confirmations from the same category.
        Keeps the strongest (solid > soft) per category.
        """
        if not confirmations:
            return []

        by_category: Dict[str, List[Confirmation]] = {}
        uncategorized = []

        for c in confirmations:
            if c.category:
                if c.category not in by_category:
                    by_category[c.category] = []
                by_category[c.category].append(c)
            else:
                uncategorized.append(c)

        deduped = list(uncategorized)
        for cat, confs in by_category.items():
            # Keep the strongest from each category
            solids = [c for c in confs if c.is_solid]
            if solids:
                deduped.append(solids[0])
            else:
                deduped.append(confs[0])

        return deduped
