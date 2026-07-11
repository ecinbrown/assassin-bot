"""
Velocity Strategy Configuration
================================
Tier-based strategy deployment using tick velocity data.
"""

# ═══════════════════════════════════════════════════
# TIER DEFINITIONS
# ═══════════════════════════════════════════════════

TIER_1_SYMBOLS = {'AEDCNY_otc'}   # Sniper: 83-93% proven WR
TIER_2_SYMBOLS = {'AUDCAD_otc', 'AUDJPY_otc'}  # Solid: 76-87% proven WR
# Tier 3: everything else (Scout mode)

def get_tier(symbol):
    if symbol in TIER_1_SYMBOLS:
        return 1
    elif symbol in TIER_2_SYMBOLS:
        return 2
    else:
        return 3

# ═══════════════════════════════════════════════════
# CANDLE WINDOWS (in minutes)
# Each tier uses specific timeframes for signal generation
# ═══════════════════════════════════════════════════

TIER_CANDLE_WINDOWS = {
    1: [3, 6, 9],      # AEDCNY: 3min, 6min, 9min
    2: [4, 6, 9],      # AUDCAD/AUDJPY: 4min, 6min, 9min
    3: [6, 9],          # Scout: 6min, 9min only (conservative)
}

# ═══════════════════════════════════════════════════
# STRATEGY PARAMETERS PER TIER
# ═══════════════════════════════════════════════════

TIER_STRATEGIES = {
    1: {
        'rsi_vel': {
            'enabled': True,
            'rsi_period': 21,
            'rsi_oversold': 5,
            'rsi_overbought': 95,
            'vel_lookback': 5,       # candles to average velocity over
            'vel_threshold': 2.5,    # velocity must be N * rolling avg
        },
        'vel_spike': {
            'enabled': True,
            'lookback': 20,          # rolling window for avg velocity
            'spike_mult': 3.0,       # velocity must be N * std above avg
        },
        'tick_density': {
            'enabled': True,
            'lookback': 10,
            'density_mult': 2.0,     # tick count N * std above avg
        },
        'vel_energy': {
            'enabled': True,
            'lookback': 10,
            'burst_mult': 3.5,       # abs_sum N * rolling avg
        },
    },
    2: {
        'rsi_vel': {
            'enabled': False,        # Not proven on tier 2 pairs
        },
        'vel_spike': {
            'enabled': True,
            'lookback': 20,
            'spike_mult': 3.5,       # More conservative
        },
        'tick_density': {
            'enabled': False,
        },
        'vel_energy': {
            'enabled': True,
            'lookback': 10,
            'burst_mult': 3.5,
        },
    },
    3: {
        'rsi_vel': {
            'enabled': False,
        },
        'vel_spike': {
            'enabled': True,
            'lookback': 20,
            'spike_mult': 3.5,       # Ultra conservative for unproven pairs
        },
        'tick_density': {
            'enabled': False,
        },
        'vel_energy': {
            'enabled': False,
        },
    },
}

# ═══════════════════════════════════════════════════
# KILL SWITCH: Auto-pause a tier if WR drops below threshold
# ═══════════════════════════════════════════════════

KILL_SWITCH = {
    'enabled': True,
    'min_trades': 20,       # Minimum trades before evaluating
    'min_win_rate': 60.0,   # Pause if WR drops below this (%)
    'window_size': 20,      # Evaluate over the last N trades
}

# ═══════════════════════════════════════════════════
# EXPIRY & COOLDOWN
# Trade expiry matches the candle window that fired the signal
# ═══════════════════════════════════════════════════

EXPIRY_MULTIPLIER = 1  # expiry = candle_window_minutes * EXPIRY_MULTIPLIER
COOLDOWN_MULTIPLIER = 1  # cooldown = expiry_seconds * COOLDOWN_MULTIPLIER
