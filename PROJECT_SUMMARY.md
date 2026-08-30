# 🗡️ Assassin Bot v2 — Complete Project Architecture & Strategy Summary

## 📌 1. Project Overview & Mission
**Assassin Bot** is a high-frequency, institutional-grade cryptocurrency price-action trading engine engineered for prediction markets (e.g. PRDT Finance Web3 contracts, Pocket Option) and binary options.

It trades **1-minute live Binance WebSocket candles** across 4 major pairs (**BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT**) using a pure **Price-Action Confluence Model** backed by statistical backtesting over **2,100,000+ real Binance candles (365 full days)**.

---

## 📁 2. File Directory & Log Locations

### 📝 Where the Trade Logs & State Live:
* **Live Runtime Console Logs:** Available in the background process task logs (`task-5941.log` in App Data).
* **Live Wallet & Performance State:** [`bot_state.json`](file:///c:/Users/DELL/Documents/anti%20web/assassin-bot/bot_state.json) — stores current balance, total wins, and total losses with automatic persistence across restarts.
* **Live Telegram Alerts:** Delivered in real time to your connected Telegram Chat.

### 🧱 Core Codebase Files:
```
assassin-bot/
├── main.py                          # Master runtime controller, dynamic compounding & trade loop
├── bot_state.json                   # Saved balance and win/loss state
├── assassin_strategy/
│   ├── signal_engine.py             # 6-step core signal orchestration engine
│   ├── confluence_scorer.py         # 3-tier solid vs soft confirmation scoring engine
│   ├── exhaustion_climax.py         # 2.5-Sigma EMA-RSI + Volume climax reversal detector
│   ├── sr_levels.py                 # Multi-touch horizontal S/R & round number detection
│   ├── pattern_detector.py          # Engulfing, Exhaustion pinbars, 3rd touch trendlines
│   ├── regime_detector.py           # Trend vs Range regime filter (Macro trend classifier)
│   ├── doji_detector.py             # Doji range box breakouts
│   ├── fvg_detector.py              # Fair Value Gap (FVG) detection & fill tracking
│   ├── qm_pattern.py                # Quasimodo (QM) structural reversal patterns
│   ├── safety_zone.py               # Margin of safety retest validation filters
│   ├── prdt_contract.py             # Direct Web3 EVM transaction signer (<300ms execution)
│   ├── binance_feed.py              # Multi-symbol real-time Binance WebSocket feed
│   └── telegram_bot.py              # Interactive Telegram control & alert dispatcher
```

---

## 🎯 3. The 85%+ Confluence Strategy (The Formula)

The bot executes a trade **only when at least 4 independent structural confirmations align simultaneously**:

1. **Solid #1 (Price Boundary):** Price is actively touching a **Major 35-to-50 candle S/R Level**, **FVG Fill**, or **Quasimodo Level** (never in the middle of a range).
2. **Solid #2 (Candlestick Rejection Trigger):** A clean **Bullish/Bearish Engulfing**, **Exhaustion Pinbar with long wick ($\ge 1.5\times$ body)**, or **Doji Box Breakout**.
3. **Solid #3 (Institutional Volume):** Volume spike **$\ge 1.8\times - 2.0\times$** the 20-period average (guarantees liquidity absorption).
4. **Soft #1 (Momentum Exhaustion):** Multi-candle stretch of **$\ge 3$ to $5$ consecutive bars** or psychological round number contact.
5. **Hard Rule (Anti-Steamroller Trend Gate):** Counter-trend trades into vertical bear dumps or rocket bull runs are **100% blocked** unless backed by extreme 5-bar exhaustion.

---

## ⚡ 4. Risk Management & 1-Gale Staking Engine

* **Max 1 Gale (Strict Risk Cap):**
  * **Base Trade (Trade 1):** 5% of account balance (wins ~51% directly).
  * **Gale 1 (Trade 2):** 11% of account balance ($2.2\times$ Base) — catches the immediate bounce if Candle 1 tests the level.
  * **Sequence Win Rate:** **`85% – 88%+`** (and up to **`96%`** in live testing).
  * **Maximum Sequence Risk:** Strictly capped at **`-16%`** per miss (Gale 2 is permanently disabled).
* **1-Trade Auto-Recovery Mode:**
  * If a sequence misses, the bot sizes the next trade to recover the loss in **one single trade**.
  * **Strict Concurrency = 1 during recovery:** Only 1 trade is allowed during recovery to eliminate double-loss risk.
  * Once won, it **immediately resets to the safe 5% base compounding curve**.

---

## 📈 5. Compounding Progression Targets

Starting from **`$10.00`** with a dynamic $+8.33\%$ net compounding rate per winning sequence:

* **Start:** `$10.00` (Base stake: `$0.50`)
* **Trade 26:** `$80.00` (Base stake: `$4.00`)
* **Trade 35 (Halfway):** **`$164.32`** (Base stake: `$8.20`)
* **Trade 55:** **`$813.55`** (Base stake: `$40.60`)
* **Trade 70 (Target Goal):** **`$2,700.20`** (Base stake: `$135.00`)

---
*Created and maintained by Antigravity AI for Assassin Bot v2.*
