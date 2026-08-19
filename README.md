# 🎯 Assassin Bot

High-probability crypto binary prediction & options engine combining smart money structure, market indecision breakouts, fair value gap imbalances, and margin-of-safety retest execution.

---

## 🏗 Architecture & Modular Components

```
assassin-bot/
├── assassin_strategy/
│   ├── __init__.py           # Package exports
│   ├── candle_utils.py       # Core candle math & inter-candle gap detector
│   ├── doji_detector.py      # Doji range box & breakout invalidation filter
│   ├── swing_detector.py     # Fractal swing high / low detection
│   ├── fvg_detector.py       # 3-candle Fair Value Gap (FVG) scanner
│   ├── qm_pattern.py         # Quasimodo (L-H-LL-HH) & Order Block detector
│   ├── safety_zone.py        # Margin of Safety & round number pending retests
│   ├── signal_engine.py      # Multi-confluence signal engine
│   ├── binance_feed.py       # Binance real-time public WebSocket kline stream
│   └── prdt_webhook.py       # PRDT Finance trade execution webhook dispatcher
├── main.py                   # Live execution orchestrator
├── backtest.py               # Historical CSV backtester
└── requirements.txt          # Lightweight dependencies (no heavy drivers)
```

---

## ⚡ Strategy Confluence Logic

1. **Doji Detection & Range Box Breakout**
   - Identifies candles where $\text{body} / \text{range} \le 10\%$.
   - Tracks a range box $[Low, High]$.
   - Breakout triggered on close outside the range.
   - **Invalidation:** Discarded if an opposing price gap occurs against the breakout direction.

2. **Quasimodo (QM) Pattern & Order Block**
   - Detects reversal sequences ($L \rightarrow H \rightarrow LL \rightarrow HH$ for bullish, $H \rightarrow L \rightarrow HH \rightarrow LL$ for bearish).
   - Identifies the Order Block at the pivot before the impulsive expansion.
   - Cross-references with active **Fair Value Gaps (FVG)** for high-probability overlap.

3. **Margin of Safety Retest Filter**
   - Replaces impulsive breakout chasing with a pending state machine.
   - Requires price to retrace and tap the safety zone (Round Number, Order Block, or QM level) before dispatching the trade.

---

## 🚀 Running Live

```bash
# Set environment variables (optional)
export TRADING_SYMBOLS="BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT"
export CANDLE_INTERVAL="1m"
export PRDT_WEBHOOK_URL="https://your-prdt-executor.com/webhook"
export PRDT_API_KEY="your_api_key"
export SIMULATION_MODE="true"  # Set false for real webhook dispatch

# Start live trading stream
python main.py
```

---

## 📊 Running Backtests

```bash
python backtest.py path/to/btcusdt_1m.csv BTCUSDT
```
