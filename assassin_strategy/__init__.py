"""
Assassin Bot - Real-Market Crypto Strategy Suite
=================================================
High-probability confluence binary options engine combining:
1. Doji Detection & Breakout Range Box
2. Gap / Overlap Confirmation Layer
3. Margin of Safety & Rejection Filter
4. Quasimodo (QM) Pattern & Order Block Imbalance Overlap
5. Binance Live WebSocket Feeder
6. PRDT Finance Webhook Dispatcher
"""
from .candle_utils import Candle, detect_gap
from .doji_detector import DojiDetector, DojiRangeBox
from .swing_detector import SwingDetector, SwingPoint
from .fvg_detector import FVGDetector, FVG
from .qm_pattern import QMPatternDetector, QMPattern, OrderBlock
from .safety_zone import MarginOfSafetyFilter, PendingSetup
from .signal_engine import AssassinSignalEngine, AssassinSignal
from .binance_feed import BinanceFeed
from .prdt_webhook import PRDTWebhookDispatcher

__all__ = [
    'Candle',
    'detect_gap',
    'DojiDetector',
    'DojiRangeBox',
    'SwingDetector',
    'SwingPoint',
    'FVGDetector',
    'FVG',
    'QMPatternDetector',
    'QMPattern',
    'OrderBlock',
    'MarginOfSafetyFilter',
    'PendingSetup',
    'AssassinSignalEngine',
    'AssassinSignal',
    'BinanceFeed',
    'PRDTWebhookDispatcher',
]
