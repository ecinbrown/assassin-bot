"""
Hybrid Signal Engine (85.07% 1-Gale Multi-Timeframe Strategy)
=============================================================
Manages real-time candle aggregation across 12 timeframes and evaluates
the 65 empirically backtested setups (Bollinger Bands, Whale Absorption,
Williams %R, CCI, Exhaustion, and Fast RSI) with verified 85.07% 1-Gale WR.
"""
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from .candle_utils import Candle

logger = logging.getLogger("HybridEngine")


@dataclass
class SetupConfig:
    pair: str
    tf: int
    type: str
    params: dict
    desc: str
    wr: float
    trades: int


class MultiTFCandleAggregator:
    """
    Synthesizes multi-minute bars (2m, 3m, 4m, 5m, 6m, 8m, 10m, 15m, 20m, 30m)
    in real time directly from incoming atomic 1m closed candles.
    """
    def __init__(self, timeframes: List[int]):
        self.timeframes = sorted(timeframes)
        # Storage: { (symbol, tf): [Candle, ...] }
        self.history: Dict[Tuple[str, int], List[Candle]] = {}
        # In-progress bars: { (symbol, tf): dict }
        self.current_bars: Dict[Tuple[str, int], dict] = {}

    def update_1m_candle(self, symbol: str, candle_1m: Candle) -> List[Tuple[int, Candle]]:
        """
        Process a 1-minute closed candle and return any multi-timeframe candles that closed.
        Returns: [ (tf, closed_candle), ... ]
        """
        closed_tf_candles = []
        sym = symbol.upper()
        
        # 1m is always closed
        key_1m = (sym, 1)
        if key_1m not in self.history:
            self.history[key_1m] = []
        self.history[key_1m].append(candle_1m)
        if len(self.history[key_1m]) > 200:
            self.history[key_1m].pop(0)
        closed_tf_candles.append((1, candle_1m))

        # Check other timeframes with clock-aligned bar boundaries
        for tf in self.timeframes:
            if tf == 1:
                continue
            key = (sym, tf)
            if key not in self.history:
                self.history[key] = []
            
            bar = self.current_bars.get(key)
            if bar is None:
                # Start new bar
                self.current_bars[key] = {
                    "open": candle_1m.open,
                    "high": candle_1m.high,
                    "low": candle_1m.low,
                    "close": candle_1m.close,
                    "volume": candle_1m.volume,
                    "trades": candle_1m.trades if hasattr(candle_1m, "trades") else 1.0,
                    "count": 1,
                    "start_time": candle_1m.timestamp
                }
                bar = self.current_bars[key]
            else:
                bar["high"] = max(bar["high"], candle_1m.high)
                bar["low"] = min(bar["low"], candle_1m.low)
                bar["close"] = candle_1m.close
                bar["volume"] += candle_1m.volume
                bar["trades"] += (candle_1m.trades if hasattr(candle_1m, "trades") else 1.0)
                bar["count"] += 1

            # Clock alignment: in Binance, a 1m candle starting at ts closes at minute (ts//60 + 1)
            # The multi-minute bar closes when that minute is a multiple of tf
            is_bar_closed = (int(candle_1m.timestamp // 60) + 1) % tf == 0
            if is_bar_closed or bar["count"] >= tf:
                final_candle = Candle(
                    open=bar["open"],
                    high=bar["high"],
                    low=bar["low"],
                    close=bar["close"],
                    volume=bar["volume"],
                    timestamp=bar["start_time"],
                    trades=bar["trades"]
                )
                self.history[key].append(final_candle)
                if len(self.history[key]) > 200:
                    self.history[key].pop(0)
                closed_tf_candles.append((tf, final_candle))
                self.current_bars[key] = None

        return closed_tf_candles


class HybridSignalEngine:
    """
    Executes real-time signal checks across all 436 high-confidence setups.
    """
    def __init__(self, config_path: Optional[str] = None):
        if config_path is None:
            config_path = os.path.join(os.path.dirname(__file__), "setups_85pct_config.json")
        
        self.setups: List[SetupConfig] = []
        self.setups_by_pair_tf: Dict[Tuple[str, int], List[SetupConfig]] = {}
        self.load_config(config_path)

        # Collect unique timeframes (always include HTF trend filter TFs: 15m, 30m, 1h, 4h)
        htf_tfs = {15, 30, 60, 240}
        timeframes = list({s.tf for s in self.setups} | htf_tfs)
        self.aggregator = MultiTFCandleAggregator(timeframes)
        logger.info(f"Initialized HybridSignalEngine with {len(self.setups)} setups across {len(timeframes)} timeframes.")

    async def preload_from_binance(self, symbols: List[str], limit: int = 1000):
        """
        Preload historical 1m candles from Binance REST API on startup.
        Feeds candles through the aggregator to instantly warm up all 19 timeframes
        (1m to 30m) with 50+ closed candles so indicators (MA20, STD20, Whale metrics)
        are ready from second 1.
        """
        import asyncio, urllib.request, json

        def fetch_sync(sym_str, iv="1m", lim=limit):
            REST_HOSTS = [
                "https://api.binance.com/api/v3/klines",
                "https://data-api.binance.vision/api/v3/klines",
                "https://api1.binance.com/api/v3/klines",
                "https://api2.binance.com/api/v3/klines",
                "https://api3.binance.com/api/v3/klines",
            ]
            for host in REST_HOSTS:
                url = f"{host}?symbol={sym_str}&interval={iv}&limit={lim}"
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                try:
                    with urllib.request.urlopen(req, timeout=8) as resp:
                        if resp.status == 200:
                            return json.loads(resp.read().decode())
                except Exception as e:
                    logger.debug(f"Preload from {host} failed for {sym_str} ({iv}): {e}")
            return []

        for sym in symbols:
            sym_upper = sym.upper()
            data = await asyncio.to_thread(fetch_sync, sym_upper, "1m", limit)
            if not data:
                logger.warning(f"⚠️ Failed to preload candles for {sym_upper}")
                continue

            for k in data:
                c = Candle(
                    timestamp=float(k[0]) / 1000.0,
                    open=float(k[1]),
                    high=float(k[2]),
                    low=float(k[3]),
                    close=float(k[4]),
                    volume=float(k[5]),
                    trades=float(k[8]) if len(k) > 8 else 1.0
                )
                self.aggregator.update_1m_candle(sym_upper, c)

            # Direct HTF warmup so 15m, 30m, 1h (60m), and 4h (240m) EMA indicators have 200 bars immediately
            htf_map = {"15m": 15, "30m": 30, "1h": 60, "4h": 240}
            for iv_str, tf_min in htf_map.items():
                htf_data = await asyncio.to_thread(fetch_sync, sym_upper, iv_str, 200)
                if htf_data:
                    candles = [
                        Candle(
                            timestamp=float(k[0]) / 1000.0,
                            open=float(k[1]),
                            high=float(k[2]),
                            low=float(k[3]),
                            close=float(k[4]),
                            volume=float(k[5]),
                            trades=float(k[8]) if len(k) > 8 else 1.0
                        )
                        for k in htf_data
                    ]
                    self.aggregator.history[(sym_upper, tf_min)] = candles[-200:]

            counts = [f"{tf}m:{len(self.aggregator.history.get((sym_upper, tf), []))}" for tf in [1, 5, 10, 15, 30, 60, 240] if tf in self.aggregator.timeframes]
            logger.critical(f"🚀 [PRELOAD COMPLETE] {sym_upper}: {len(data)} 1m + HTF klines processed -> Warmed up: {', '.join(counts)}")

    def load_config(self, path: str):
        with open(path, "r") as f:
            raw = json.load(f)
        for item in raw:
            s = SetupConfig(
                pair=item["pair"].upper(),
                tf=item["tf"],
                type=item["type"],
                params=item["params"],
                desc=item["desc"],
                wr=item["wr"],
                trades=item["trades"]
            )
            self.setups.append(s)
            key = (s.pair, s.tf)
            if key not in self.setups_by_pair_tf:
                self.setups_by_pair_tf[key] = []
            self.setups_by_pair_tf[key].append(s)

    def preload_history(self, symbol: str, tf: int, candles: List[Candle]):
        """Seed history for indicator stabilization on bot startup."""
        key = (symbol.upper(), tf)
        self.aggregator.history[key] = list(candles[-200:])

    def evaluate_setups(self, symbol: str, tf: int, candle: Candle) -> List[dict]:
        """
        Evaluate any setups registered for (symbol, tf).
        Returns list of signal dicts.
        """
        sym = symbol.upper()
        setups = self.setups_by_pair_tf.get((sym, tf), [])
        if not setups:
            return []

        history = self.aggregator.history.get((sym, tf), [])
        if len(history) < 20:
            return []

        closes = np.array([c.close for c in history], dtype=float)
        opens = np.array([c.open for c in history], dtype=float)
        highs = np.array([c.high for c in history], dtype=float)
        lows = np.array([c.low for c in history], dtype=float)
        volumes = np.array([c.volume for c in history], dtype=float)
        trades_arr = np.array([getattr(c, "trades", 1.0) for c in history], dtype=float)
        n = len(closes)

        # 1. Price Action Wicks
        curr_rng = max(highs[-1] - lows[-1], 1e-8)
        lw = (min(opens[-1], closes[-1]) - lows[-1]) / curr_rng
        uw = (highs[-1] - max(opens[-1], closes[-1])) / curr_rng

        # 2. Institutional Whale Metric
        sizes = volumes / np.maximum(trades_arr, 1.0)
        size_sma = np.mean(sizes[-50:]) if n >= 50 else np.mean(sizes)
        whale = sizes[-1] / max(size_sma, 1e-8)

        # 3. Volume Ratio
        vol_sma = np.mean(volumes[-50:]) if n >= 50 else np.mean(volumes)
        v_ratio = volumes[-1] / max(vol_sma, 1e-8)

        # 4. Bollinger Bands (20-period)
        ma20 = np.mean(closes[-20:])
        std20 = np.std(closes[-20:])

        # 5. Consecutive bars
        cr = 0; cg = 0
        for i in range(n - 1, -1, -1):
            if closes[i] < opens[i]:
                cr += 1
            else:
                break
        for i in range(n - 1, -1, -1):
            if closes[i] > opens[i]:
                cg += 1
            else:
                break

        # 6. Body and Wick Ratios
        body_ratio = abs(closes[-1] - opens[-1]) / max(curr_rng, 1e-8)

        # 7. Bollinger Z-score
        bb_z = (closes[-1] - ma20) / max(std20, 1e-8)

        # 8. Volume SMA20 ratio (already have v_ratio from vol_sma)
        vol_sma20 = np.mean(volumes[-20:]) if n >= 20 else np.mean(volumes)
        vol_ratio_20 = volumes[-1] / max(vol_sma20, 1e-8)

        # 9. MFI (14-period Money Flow Index)
        mfi_val = 50.0
        if n >= 15:
            tp = (highs[-14:] + lows[-14:] + closes[-14:]) / 3.0
            tp_prev = np.roll(tp, 1)
            mf = tp * volumes[-14:]
            pos_flow = np.sum(mf[1:][tp[1:] > tp_prev[1:]])
            neg_flow = np.sum(mf[1:][tp[1:] < tp_prev[1:]])
            if neg_flow > 0:
                mfi_val = 100.0 - (100.0 / (1.0 + pos_flow / neg_flow))

        def _get_htf_trend_state(trend_str: str) -> tuple:
            # Parse trend string: e.g. '15m_EMA20', '30m_EMA20', '1h_EMA50', '4h_EMA50'
            parts = trend_str.split("_")
            htf_s = parts[0]
            span = int(parts[1].replace("EMA", "")) if len(parts) > 1 else 20
            if htf_s.endswith("h"):
                h_min = int(htf_s[:-1]) * 60
            elif htf_s.endswith("m"):
                h_min = int(htf_s[:-1])
            else:
                h_min = 15

            h_hist = self.aggregator.history.get((sym, h_min), [])
            if len(h_hist) >= span:
                c_vals = [c.close for c in h_hist]
                a = 2.0 / (span + 1.0)
                e_val = c_vals[0]
                for cv in c_vals[1:]:
                    e_val = a * cv + (1.0 - a) * e_val
                return (c_vals[-1] > e_val and closes[-1] > e_val), (c_vals[-1] < e_val and closes[-1] < e_val), htf_s, e_val
            else:
                return closes[-1] > ma20, closes[-1] < ma20, "1m", ma20

        signals = []

        for s in setups:
            try:
                stype = s.type
                p = s.params or {}
                action = None
                trigger_detail = ""

                # ─── BOLLINGER BANDS ───
                if stype == "BB":
                    std_m = float(p.get("std", p.get("bb_th", 2.0)))
                    wick_req = float(p.get("wick", p.get("min_wick", 0.0)))
                    whale_req = float(p.get("whale", 0.0))
                    bb_u = ma20 + std_m * std20
                    bb_l = ma20 - std_m * std20

                    if closes[-1] < bb_l and lw >= wick_req and whale >= whale_req:
                        action = "call"
                        trigger_detail = f"Close<{bb_l:.2f} | LW={lw:.2f}>={wick_req} | Whale={whale:.1f}>={whale_req}"
                    elif closes[-1] > bb_u and uw >= wick_req and whale >= whale_req:
                        action = "put"
                        trigger_detail = f"Close>{bb_u:.2f} | UW={uw:.2f}>={wick_req} | Whale={whale:.1f}>={whale_req}"

                # ─── RSI ───
                elif stype == "RSI":
                    period = int(p.get("period", p.get("rsi_period", 14)))
                    lo_th = float(p.get("lo", p.get("rsi_th", 30)))
                    hi_th = float(p.get("hi", 100 - lo_th))
                    whale_req = float(p.get("whale", 0.0))

                    deltas = np.diff(closes[-(period + 30):])
                    gains = np.where(deltas > 0, deltas, 0.0)
                    losses = np.where(deltas < 0, -deltas, 0.0)
                    ag = np.mean(gains[:period])
                    al = np.mean(losses[:period])
                    for j in range(period, len(deltas)):
                        ag = (ag * (period - 1) + gains[j]) / period
                        al = (al * (period - 1) + losses[j]) / period
                    rsi_val = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

                    if rsi_val <= lo_th and whale >= whale_req:
                        action = "call"
                        trigger_detail = f"RSI{period}={rsi_val:.1f}<={lo_th} | Whale={whale:.1f}>={whale_req}"
                    elif rsi_val >= hi_th and whale >= whale_req:
                        action = "put"
                        trigger_detail = f"RSI{period}={rsi_val:.1f}>={hi_th} | Whale={whale:.1f}>={whale_req}"

                # ─── WILLIAMS %R (Direct & Confluence) ───
                elif stype == "WILLR":
                    wr_th = float(p.get("wr_th", 92))
                    bb_th = float(p.get("bb_th", 0.0))
                    vol_th = float(p.get("vol", p.get("min_vol", 0.0)))
                    wick_req = float(p.get("wick", p.get("min_wick", 0.0)))
                    whale_req = float(p.get("whale", 0.0))

                    hh = np.max(highs[-14:])
                    ll = np.min(lows[-14:])
                    diff = hh - ll
                    wr14 = -50.0 if diff < 1e-8 else -100.0 * (hh - closes[-1]) / diff

                    # Check HTF trend if specified
                    trend_req = p.get("trend")
                    b_bull, b_bear = True, True
                    if trend_req:
                        b_bull, b_bear, _, _ = _get_htf_trend_state(trend_req)

                    bb_call = (bb_th <= 0.0) or (bb_z <= -bb_th)
                    bb_put = (bb_th <= 0.0) or (bb_z >= bb_th)
                    vol_ok = (vol_th <= 0.0) or (vol_ratio_20 >= vol_th)

                    if b_bull and wr14 <= -wr_th and bb_call and vol_ok and lw >= wick_req and whale >= whale_req:
                        action = "call"
                        trigger_detail = f"WillR={wr14:.1f}<=-{wr_th} | BBz={bb_z:.2f} | Vol={vol_ratio_20:.1f}x"
                    elif b_bear and wr14 >= -(100 - wr_th) and bb_put and vol_ok and uw >= wick_req and whale >= whale_req:
                        action = "put"
                        trigger_detail = f"WillR={wr14:.1f}>=-{100 - wr_th} | BBz={bb_z:.2f} | Vol={vol_ratio_20:.1f}x"

                # ─── CCI (Direct & Confluence) ───
                elif stype == "CCI":
                    cci_th = float(p.get("cci_th", 150))
                    bb_th = float(p.get("bb_th", 0.0))
                    whale_req = float(p.get("whale", 0.0))

                    # 14 or 20 period CCI
                    tp = (highs[-14:] + lows[-14:] + closes[-14:]) / 3.0
                    ma = np.mean(tp)
                    md = np.mean(np.abs(tp - ma))
                    cci_val = 0.0 if md < 1e-8 else (tp[-1] - ma) / (0.015 * md)

                    trend_req = p.get("trend")
                    b_bull, b_bear = True, True
                    if trend_req:
                        b_bull, b_bear, _, _ = _get_htf_trend_state(trend_req)

                    bb_call = (bb_th <= 0.0) or (bb_z <= -bb_th)
                    bb_put = (bb_th <= 0.0) or (bb_z >= bb_th)

                    if b_bull and cci_val <= -cci_th and bb_call and whale >= whale_req:
                        action = "call"
                        trigger_detail = f"CCI={cci_val:.1f}<=-{cci_th} | BBz={bb_z:.2f}"
                    elif b_bear and cci_val >= cci_th and bb_put and whale >= whale_req:
                        action = "put"
                        trigger_detail = f"CCI={cci_val:.1f}>={cci_th} | BBz={bb_z:.2f}"

                # ─── EXHAUSTION + VOL CLIMAX ───
                elif stype == "EXHAUSTION":
                    bars_req = int(p.get("bars", 3))
                    vol_req = float(p.get("vol", 1.5))

                    if cr >= bars_req and v_ratio >= vol_req and lw >= 0.25:
                        action = "call"
                        trigger_detail = f"ConsecRed={cr}>={bars_req} | Vol={v_ratio:.1f}x>={vol_req} | LW={lw:.2f}>=0.25"
                    elif cg >= bars_req and v_ratio >= vol_req and uw >= 0.25:
                        action = "put"
                        trigger_detail = f"ConsecGreen={cg}>={bars_req} | Vol={v_ratio:.1f}x>={vol_req} | UW={uw:.2f}>=0.25"

                # ─── STOCHASTIC (Direct & Confluence) ───
                elif stype == "STOCH":
                    st_th = float(p.get("st_th", 10))
                    bb_th = float(p.get("bb_th", 0.0))
                    whale_req = float(p.get("whale", 0.0))

                    hh = np.max(highs[-14:])
                    ll = np.min(lows[-14:])
                    diff = hh - ll
                    stoch_val = 50.0 if diff < 1e-8 else (closes[-1] - ll) / diff * 100.0

                    trend_req = p.get("trend")
                    b_bull, b_bear = True, True
                    if trend_req:
                        b_bull, b_bear, _, _ = _get_htf_trend_state(trend_req)

                    bb_call = (bb_th <= 0.0) or (bb_z <= -bb_th)
                    bb_put = (bb_th <= 0.0) or (bb_z >= bb_th)

                    if b_bull and stoch_val <= st_th and bb_call and whale >= whale_req:
                        action = "call"
                        trigger_detail = f"Stoch14={stoch_val:.1f}<={st_th} | BBz={bb_z:.2f}"
                    elif b_bear and stoch_val >= (100 - st_th) and bb_put and whale >= whale_req:
                        action = "put"
                        trigger_detail = f"Stoch14={stoch_val:.1f}>={100 - st_th} | BBz={bb_z:.2f}"

                # ─── BB + RSI REVERSAL (No-Gale) ───
                elif stype == "BB_RSI_REV":
                    rsi_period = p.get("rsi_period", 14)
                    rsi_th = p.get("rsi_th", 5)
                    bb_th = p.get("bb_th", 2.5)
                    min_vol = p.get("min_vol", 0.0)

                    deltas = np.diff(closes[-(rsi_period + 30):])
                    gains = np.where(deltas > 0, deltas, 0.0)
                    losses_arr = np.where(deltas < 0, -deltas, 0.0)
                    ag = np.mean(gains[:rsi_period])
                    al = np.mean(losses_arr[:rsi_period])
                    for j in range(rsi_period, len(deltas)):
                        ag = (ag * (rsi_period - 1) + gains[j]) / rsi_period
                        al = (al * (rsi_period - 1) + losses_arr[j]) / rsi_period
                    rsi_val = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

                    if rsi_val <= rsi_th and bb_z <= -bb_th and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "call"
                        trigger_detail = f"RSI{rsi_period}={rsi_val:.1f}<={rsi_th} | BBz={bb_z:.2f}<=-{bb_th} | Vol={vol_ratio_20:.1f}"
                    elif rsi_val >= (100 - rsi_th) and bb_z >= bb_th and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "put"
                        trigger_detail = f"RSI{rsi_period}={rsi_val:.1f}>={100-rsi_th} | BBz={bb_z:.2f}>={bb_th} | Vol={vol_ratio_20:.1f}"

                # ─── RSI ONLY (No-Gale) ───
                elif stype == "RSI_ONLY":
                    rsi_period = p.get("rsi_period", 2)
                    rsi_th = p.get("rsi_th", 3)
                    min_vol = p.get("min_vol", 0.0)

                    deltas = np.diff(closes[-(rsi_period + 30):])
                    gains = np.where(deltas > 0, deltas, 0.0)
                    losses_arr = np.where(deltas < 0, -deltas, 0.0)
                    ag = np.mean(gains[:rsi_period])
                    al = np.mean(losses_arr[:rsi_period])
                    for j in range(rsi_period, len(deltas)):
                        ag = (ag * (rsi_period - 1) + gains[j]) / rsi_period
                        al = (al * (rsi_period - 1) + losses_arr[j]) / rsi_period
                    rsi_val = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

                    if rsi_val <= rsi_th and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "call"
                        trigger_detail = f"RSI{rsi_period}={rsi_val:.1f}<={rsi_th} | Vol={vol_ratio_20:.1f}"
                    elif rsi_val >= (100 - rsi_th) and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "put"
                        trigger_detail = f"RSI{rsi_period}={rsi_val:.1f}>={100-rsi_th} | Vol={vol_ratio_20:.1f}"

                # ─── BB + STREAK (No-Gale) ───
                elif stype == "BB_STREAK":
                    bb_th = p.get("bb_th", 2.5)
                    min_run = p.get("min_run", 3)
                    min_vol = p.get("min_vol", 0.0)

                    if bb_z <= -bb_th and cr >= min_run and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "call"
                        trigger_detail = f"BBz={bb_z:.2f}<=-{bb_th} | RedStreak={cr}>={min_run} | Vol={vol_ratio_20:.1f}"
                    elif bb_z >= bb_th and cg >= min_run and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "put"
                        trigger_detail = f"BBz={bb_z:.2f}>={bb_th} | GreenStreak={cg}>={min_run} | Vol={vol_ratio_20:.1f}"

                # ─── WICK REJECTION (No-Gale) ───
                elif stype == "WICK_REJ":
                    min_wick = p.get("min_wick", 0.5)
                    max_body = p.get("max_body", 0.3)
                    bb_th = p.get("bb_th", 0.0)
                    min_vol = p.get("min_vol", 0.0)

                    bb_ok_call = (bb_th <= 0) or (bb_z <= -bb_th)
                    bb_ok_put = (bb_th <= 0) or (bb_z >= bb_th)

                    if lw >= min_wick and body_ratio <= max_body and bb_ok_call and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "call"
                        trigger_detail = f"LW={lw:.2f}>={min_wick} | Body={body_ratio:.2f}<={max_body} | BBz={bb_z:.2f}"
                    elif uw >= min_wick and body_ratio <= max_body and bb_ok_put and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "put"
                        trigger_detail = f"UW={uw:.2f}>={min_wick} | Body={body_ratio:.2f}<={max_body} | BBz={bb_z:.2f}"

                # ─── MFI + RSI (No-Gale) ───
                elif stype == "MFI_RSI":
                    mfi_th = p.get("mfi_th", 20)
                    rsi_period = p.get("rsi_period", 5)
                    rsi_th = p.get("rsi_th", 10)
                    min_vol = p.get("min_vol", 0.0)

                    deltas = np.diff(closes[-(rsi_period + 30):])
                    gains = np.where(deltas > 0, deltas, 0.0)
                    losses_arr = np.where(deltas < 0, -deltas, 0.0)
                    ag = np.mean(gains[:rsi_period])
                    al = np.mean(losses_arr[:rsi_period])
                    for j in range(rsi_period, len(deltas)):
                        ag = (ag * (rsi_period - 1) + gains[j]) / rsi_period
                        al = (al * (rsi_period - 1) + losses_arr[j]) / rsi_period
                    rsi_val = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

                    if mfi_val <= mfi_th and rsi_val <= rsi_th and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "call"
                        trigger_detail = f"MFI={mfi_val:.1f}<={mfi_th} | RSI{rsi_period}={rsi_val:.1f}<={rsi_th}"
                    elif mfi_val >= (100 - mfi_th) and rsi_val >= (100 - rsi_th) and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "put"
                        trigger_detail = f"MFI={mfi_val:.1f}>={100-mfi_th} | RSI{rsi_period}={rsi_val:.1f}>={100-rsi_th}"

                # ─── EXTREME REVERSAL (Strict Zero-Gale Champions: 70-89% WR Verified) ───
                elif stype in ("EXTREME_REVERSAL", "SNIPER_NO_GALE"):
                    rsi_period = int(p.get("rsi_period", 7))
                    rsi_th = float(p.get("rsi_th", 10.0))
                    bb_th = float(p.get("bb_th", 2.0))
                    min_wick = float(p.get("min_wick", 0.0))
                    min_vol = float(p.get("min_vol", 0.0))

                    deltas = np.diff(closes[-(rsi_period + 30):])
                    gains = np.where(deltas > 0, deltas, 0.0)
                    losses_arr = np.where(deltas < 0, -deltas, 0.0)
                    ag = np.mean(gains[:rsi_period])
                    al = np.mean(losses_arr[:rsi_period])
                    for j in range(rsi_period, len(deltas)):
                        ag = (ag * (rsi_period - 1) + gains[j]) / rsi_period
                        al = (al * (rsi_period - 1) + losses_arr[j]) / rsi_period
                    rsi_val = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

                    if rsi_val <= rsi_th and bb_z <= -bb_th and lw >= min_wick and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "call"
                        trigger_detail = f"RSI{rsi_period}={rsi_val:.1f}<={rsi_th} | BBz={bb_z:.2f}<=-{bb_th} | LW={lw:.2f}>={min_wick}"
                    elif rsi_val >= (100.0 - rsi_th) and bb_z >= bb_th and uw >= min_wick and (min_vol <= 0 or vol_ratio_20 >= min_vol):
                        action = "put"
                        trigger_detail = f"RSI{rsi_period}={rsi_val:.1f}>={100.0-rsi_th} | BBz={bb_z:.2f}>={bb_th} | UW={uw:.2f}>={min_wick}"

                # ─── HTF TREND PULLBACK (Multi-Bar No-Gale 83%WR 55TPD) ───
                elif stype == "HTF_PULLBACK":
                    trend_type = p.get("trend", "15m_EMA20")
                    rsi_p = int(p.get("rsi_period", 7))
                    rsi_th = float(p.get("rsi_th", 25.0))
                    bb_th = float(p.get("bb_th", 2.0))
                    min_wick = float(p.get("min_wick", 0.0))
                    min_vol = float(p.get("min_vol", 1.0))

                    # Parse trend string: "15m_EMA20", "30m_EMA20", "1h_EMA50", "4h_EMA50"
                    trend_parts = trend_type.split("_")
                    htf_str = trend_parts[0]  # e.g. "15m", "30m", "1h", "4h"
                    ema_str = trend_parts[1] if len(trend_parts) > 1 else "EMA20"
                    span = int(ema_str.replace("EMA", ""))

                    # Convert HTF string to minutes for aggregator lookup
                    if htf_str.endswith("h"):
                        htf_min = int(htf_str[:-1]) * 60
                    elif htf_str.endswith("m"):
                        htf_min = int(htf_str[:-1])
                    else:
                        htf_min = 15

                    htf_history = self.aggregator.history.get((sym, htf_min), [])
                    if len(htf_history) >= span:
                        c_htf = [c.close for c in htf_history]
                        alpha = 2.0 / (span + 1.0)
                        ema_htf = c_htf[0]
                        for c_val in c_htf[1:]:
                            ema_htf = alpha * c_val + (1.0 - alpha) * ema_htf
                        is_bull = (c_htf[-1] > ema_htf) and (closes[-1] > ema_htf)
                        is_bear = (c_htf[-1] < ema_htf) and (closes[-1] < ema_htf)
                    else:
                        is_bull = closes[-1] > ma20
                        is_bear = closes[-1] < ma20
                        ema_htf = ma20

                    # RSI on current timeframe
                    deltas = np.diff(closes[-(rsi_p + 30):])
                    gains = np.where(deltas > 0, deltas, 0.0)
                    losses_arr = np.where(deltas < 0, -deltas, 0.0)
                    ag = np.mean(gains[:rsi_p])
                    al = np.mean(losses_arr[:rsi_p])
                    for j in range(rsi_p, len(deltas)):
                        ag = (ag * (rsi_p - 1) + gains[j]) / rsi_p
                        al = (al * (rsi_p - 1) + losses_arr[j]) / rsi_p
                    rsi_val = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)

                    if is_bull and rsi_val <= rsi_th and bb_z <= -bb_th and lw >= min_wick and vol_ratio_20 >= min_vol:
                        action = "call"
                        trigger_detail = f"{htf_str}Bull(C>{ema_htf:.1f}) | RSI{rsi_p}={rsi_val:.1f}<={rsi_th} | BBz={bb_z:.2f}<=-{bb_th} | Vol={vol_ratio_20:.1f}"
                    elif is_bear and rsi_val >= (100.0 - rsi_th) and bb_z >= bb_th and uw >= min_wick and vol_ratio_20 >= min_vol:
                        action = "put"
                        trigger_detail = f"{htf_str}Bear(C<{ema_htf:.1f}) | RSI{rsi_p}={rsi_val:.1f}>={100.0-rsi_th} | BBz={bb_z:.2f}>={bb_th} | Vol={vol_ratio_20:.1f}"

                if action:
                    # Support variable expiry_bars from config (default: 1 bar)
                    expiry_bars = s.params.get("expiry_bars", 1) if hasattr(s, 'params') else 1
                    # Also check top-level expiry_bars on the setup dict during load
                    if hasattr(s, 'expiry_bars'):
                        expiry_bars = s.expiry_bars
                    signals.append({
                        "symbol": sym,
                        "action": action,
                        "price": closes[-1],
                        "tf": tf,
                        "expiry_seconds": tf * 60 * max(expiry_bars, 1),
                        "confidence": s.wr / 100.0,
                        "pattern_type": f"{s.type}_{tf}M",
                        "trigger": f"{s.desc} | {trigger_detail}",
                        "setup": s
                    })
                    logger.info(f"🎯 [HYBRID SIGNAL] {sym} {action.upper()} on {tf}m bar | WR: {s.wr}% | {s.desc}")
            except Exception as e:
                logger.error(f"Error evaluating setup {getattr(s, 'desc', s)}: {e}")

        return signals
