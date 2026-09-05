"""
Doji Detection & Breakout Range Box Module
==========================================
Identifies indecision Doji candles, maintains breakout range boxes,
and handles directional invalidation rules.
"""
from numpy import append
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from .candle_utils import Candle, detect_gap


@dataclass
class DojiRangeBox:
    symbol: str
    doji_timestamp: float
    high: float
    low: float
    open_price: float
    close_price: float
    candle_idx: int
    active: bool = True
    breakout_dir: Optional[str] = None  # 'call' or 'put'
    breakout_price: Optional[float] = None
    breakout_idx: Optional[int] = None
    invalidated: bool = False
    invalidation_reason: str = ""

    @property
    def range_height(self) -> float:
        return self.high - self.low


class DojiDetector:
    def __init__(self, body_threshold: float = 0.10, max_box_age_candles: int = 15):
        """
        Args:
            body_threshold: Max body/range ratio to qualify as a Doji (default 10%).
            max_box_age_candles: Maximum candles to keep a Doji range box active before expiration.
        """
        self.body_threshold = body_threshold
        self.max_box_age = max_box_age_candles
        # {symbol: list of active DojiRangeBox}
        self.active_boxes: Dict[str, List[DojiRangeBox]] = {}

    def is_doji(self, candle: Candle) -> bool:
        """Check if a single candle matches the Doji ratio criteria."""
        if candle.total_range <= 0:
            return False
        return candle.body_ratio <= self.body_threshold

    def process_candle(
        self, symbol: str, current_candle: Candle, prev_candle: Optional[Candle], current_idx: int
    ) -> List[Tuple[DojiRangeBox, str, str]]:
        """
        Process a new closed candle for Dojis, range breakouts, and gap invalidations.
        
        Returns:
            List of tuples: (range_box, action: 'call'|'put', trigger_description)
        """
        if symbol not in self.active_boxes:
            self.active_boxes[symbol] = []

        confirmed_signals: List[Tuple[DojiRangeBox, str, str]] = []

        # 1. Detect gap between previous and current candle
        gap_type, gap_size, gap_pct = ('none', 0.0, 0.0)
        if prev_candle:
            gap_type, gap_size, gap_pct = detect_gap(current_candle, prev_candle)

        # 2. Check existing active Doji boxes for breakouts or invalidation
        still_active: List[DojiRangeBox] = []
        for box in self.active_boxes[symbol]:
            # Age expiration
            if current_idx - box.candle_idx > self.max_box_age:
                continue

            # Invalidation Check:
            # If gap occurred against expected direction, invalidate
            if box.breakout_dir == 'call' and gap_type == 'gap_down':
                box.invalidated = True
                box.invalidation_reason = f"Opposing gap down ({gap_pct:.2f}%) invalidated bullish breakout"
                continue
            elif box.breakout_dir == 'put' and gap_type == 'gap_up':
                box.invalidated = True
                box.invalidation_reason = f"Opposing gap up ({gap_pct:.2f}%) invalidated bearish breakout"
                continue

            # Breakout Detection
            if box.breakout_dir is None:
                if current_candle.close > box.high:
                    # Bullish Breakout
                    if gap_type == 'gap_down':
                        # Invalidated at birth by opposing gap
                        box.invalidated = True
                        box.invalidation_reason = "Gap down against bullish breakout"
                        continue
                    box.breakout_dir = 'call'
                    box.breakout_price = current_candle.close
                    box.breakout_idx = current_idx
                    confirmed_signals.append(
                        (box, 'call', f"Doji Bullish Breakout above {box.high:.2f}")
                    )
                elif current_candle.close < box.low:
                    # Bearish Breakout
                    if gap_type == 'gap_up':
                        # Invalidated at birth by opposing gap
                        box.invalidated = True
                        box.invalidation_reason = "Gap up against bearish breakout"
                        continue
                    box.breakout_dir = 'put'
                    box.breakout_price = current_candle.close
                    box.breakout_idx = current_idx
                    confirmed_signals.append(
                        (box, 'put', f"Doji Bearish Breakout below {box.low:.2f}")
                    )

            still_active.append(box)

        self.active_boxes[symbol] = still_active

        # 3. If the current candle itself is a Doji, register a new range box
        if self.is_doji(current_candle):
            new_box = DojiRangeBox(
                symbol=symbol,
                doji_timestamp=current_candle.timestamp,
                high=current_candle.high,
                low=current_candle.low,
                open_price=current_candle.open,
                close_price=current_candle.close,
                candle_idx=current_idx
            )
            self.active_boxes[symbol].append(new_box)

        return confirmed_signals
