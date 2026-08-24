"""
Assassin Bot - Real-Market Crypto Strategy Suite v2
====================================================
Full Price-Action Confluence Engine — no indicators, raw structure only:
1. Doji Detection & Breakout Range Box
2. Fair Value Gap (FVG) Imbalance Zones
3. Quasimodo (QM) Pattern & Order Block
4. Exhaustion Candle, Engulfing, Spinning Top, Third Touch
5. Support/Resistance Zones & Round Number Levels
6. Market Regime Detection (Trending vs Ranging)
7. Confluence Scoring Engine (Take It / Lean / Leave It)
8. Margin of Safety Pending Retest Filter
9. Binance Live WebSocket Feeder
10. PRDT Finance Webhook Dispatcher
"""
from .candle_utils import Candle, detect_gap
from .doji_detector import DojiDetector, DojiRangeBox
from .swing_detector import SwingDetector, SwingPoint
from .fvg_detector import FVGDetector, FVG
from .qm_pattern import QMPatternDetector, QMPattern, OrderBlock
from .safety_zone import MarginOfSafetyFilter, PendingSetup
from .pattern_detector import PatternDetector, PatternSignal
from .sr_levels import SRDetector, SRLevel
from .regime_detector import RegimeDetector, MarketRegime, MarketState
from .confluence_scorer import ConfluenceScorer, Confirmation, ConfluenceVerdict
from .signal_engine import AssassinSignalEngine, AssassinSignal
from .exhaustion_climax import ExhaustionClimaxDetector, ExhaustionClimaxSignal
from .binance_feed import BinanceFeed
from .prdt_webhook import PRDTWebhookDispatcher
from .prdt_contract import PRDTAgent, EnteredRound
from .telegram_bot import AssassinTelegramBot

__all__ = [
    'Candle', 'detect_gap',
    'DojiDetector', 'DojiRangeBox',
    'SwingDetector', 'SwingPoint',
    'FVGDetector', 'FVG',
    'QMPatternDetector', 'QMPattern', 'OrderBlock',
    'MarginOfSafetyFilter', 'PendingSetup',
    'PatternDetector', 'PatternSignal',
    'SRDetector', 'SRLevel',
    'RegimeDetector', 'MarketRegime', 'MarketState',
    'ConfluenceScorer', 'Confirmation', 'ConfluenceVerdict',
    'ExhaustionClimaxDetector', 'ExhaustionClimaxSignal',
    'AssassinSignalEngine', 'AssassinSignal',
    'BinanceFeed', 'PRDTWebhookDispatcher',
    'PRDTAgent', 'EnteredRound',
    'AssassinTelegramBot',
]
