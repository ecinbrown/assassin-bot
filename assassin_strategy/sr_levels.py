"""
Support/Resistance Level Detection Module
==========================================
Identifies horizontal S/R zones where price has reversed 2+ times,
plus psychological round number levels (.00 and .50).
"""
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import math
from .candle_utils import Candle


@dataclass
class SRLevel:
    price: float
    level_type: str       # 'support', 'resistance', or 'round_number'
    touches: int          # Number of times price reversed at this level
    touch_indices: List[int] = field(default_factory=list)
    strength: str = 'weak'  # 'weak' (1-2 touches), 'strong' (3+), 'major' (5+)
    zone_low: float = 0.0
    zone_high: float = 0.0

    def is_price_at_level(self, price: float, tolerance_pct: float = 0.10) -> bool:
        """Check if price is touching this S/R level."""
        diff = abs(price - self.price) / self.price * 100.0 if self.price > 0 else 999
        return diff <= tolerance_pct

    def is_price_in_zone(self, price: float) -> bool:
        return self.zone_low <= price <= self.zone_high


class SRDetector:
    """
    Horizontal Support/Resistance zone detection.
    
    Algorithm:
    1. Cluster swing highs and swing lows into price zones.
    2. Zones with 2+ touches become S/R levels.
    3. More touches = stronger level.
    """

    def __init__(self, cluster_tolerance_pct: float = 0.15, min_touches: int = 2):
        self.cluster_tolerance_pct = cluster_tolerance_pct
        self.min_touches = min_touches

    def detect_levels(self, candles: List[Candle]) -> List[SRLevel]:
        """Scan candle history and return all active S/R levels."""
        from .swing_detector import SwingDetector
        detector = SwingDetector(left_bars=2, right_bars=2)
        swings = detector.find_swings(candles)

        if not swings:
            return []

        # Collect all pivot prices with their indices and type
        pivot_data = [(s.price, s.index, s.point_type) for s in swings]

        # Cluster pivots into zones
        levels: List[SRLevel] = []
        used = set()

        for i, (price_i, idx_i, type_i) in enumerate(pivot_data):
            if i in used:
                continue

            cluster_prices = [price_i]
            cluster_indices = [idx_i]
            cluster_types = [type_i]
            used.add(i)

            for j in range(i + 1, len(pivot_data)):
                if j in used:
                    continue
                price_j, idx_j, type_j = pivot_data[j]
                pct_diff = abs(price_j - price_i) / price_i * 100 if price_i > 0 else 999
                if pct_diff <= self.cluster_tolerance_pct:
                    cluster_prices.append(price_j)
                    cluster_indices.append(idx_j)
                    cluster_types.append(type_j)
                    used.add(j)

            if len(cluster_prices) >= self.min_touches:
                avg_price = sum(cluster_prices) / len(cluster_prices)
                zone_low = min(cluster_prices)
                zone_high = max(cluster_prices)

                # Determine S/R type based on majority of pivot types
                sl_count = sum(1 for t in cluster_types if t == 'SL')
                sh_count = sum(1 for t in cluster_types if t == 'SH')
                level_type = 'support' if sl_count >= sh_count else 'resistance'

                touches = len(cluster_prices)
                if touches >= 5:
                    strength = 'major'
                elif touches >= 3:
                    strength = 'strong'
                else:
                    strength = 'weak'

                levels.append(SRLevel(
                    price=avg_price,
                    level_type=level_type,
                    touches=touches,
                    touch_indices=sorted(cluster_indices),
                    strength=strength,
                    zone_low=zone_low,
                    zone_high=zone_high
                ))

        # Sort by strength (most touches first)
        levels.sort(key=lambda x: x.touches, reverse=True)
        return levels

    @staticmethod
    def find_round_numbers(price: float, count: int = 4) -> List[SRLevel]:
        """
        Find psychological round numbers (.00 and .50 levels) near current price.
        These act as natural S/R magnets.
        """
        levels = []

        # Determine step size based on price magnitude
        if price >= 10000:
            steps = [500.0, 1000.0]   # BTC: 68000, 68500, 69000
        elif price >= 1000:
            steps = [50.0, 100.0]     # ETH: 2500, 2550, 2600
        elif price >= 100:
            steps = [5.0, 10.0]       # SOL: 140, 145, 150
        elif price >= 10:
            steps = [0.50, 1.0]       # e.g. 12.00, 12.50
        elif price >= 1.0:
            steps = [0.10, 0.50]
        else:
            steps = [0.01, 0.05]

        for step in steps:
            lower = math.floor(price / step) * step
            for offset in range(-count // 2, count // 2 + 1):
                rn_price = round(lower + offset * step, 8)
                if rn_price > 0:
                    levels.append(SRLevel(
                        price=rn_price,
                        level_type='round_number',
                        touches=0,
                        strength='psychological',
                        zone_low=rn_price - step * 0.01,
                        zone_high=rn_price + step * 0.01
                    ))

        # Deduplicate by price
        seen = set()
        unique = []
        for lv in levels:
            key = round(lv.price, 6)
            if key not in seen:
                seen.add(key)
                unique.append(lv)

        return unique

    def is_at_key_level(self, price: float, candles: List[Candle], tolerance_pct: float = 0.15) -> Tuple[bool, Optional[SRLevel]]:
        """
        Quick check: is the current price touching any key S/R or round number level?
        Returns (True, level) or (False, None).
        """
        sr_levels = self.detect_levels(candles)
        round_numbers = self.find_round_numbers(price)

        for lv in sr_levels + round_numbers:
            if lv.is_price_at_level(price, tolerance_pct):
                return True, lv

        return False, None
