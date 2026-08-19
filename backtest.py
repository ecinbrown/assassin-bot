"""
Assassin Strategy Historical Backtester
=======================================
Backtests the complete Assassin confluence suite against Binance historical CSV kline data.
"""
import csv
import glob
import os
import sys
import time
from typing import List

from assassin_strategy import Candle, AssassinSignalEngine, AssassinSignal


def load_candles_from_csv(filepath: str, max_rows: int = 150000) -> List[Candle]:
    candles = []
    if not os.path.exists(filepath):
        return candles

    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not row or len(row) < 5:
                continue
            try:
                # Handles timestamp, open, high, low, close, volume formats
                ts = float(row[0]) if float(row[0]) < 1e12 else float(row[0]) / 1000.0
                c = Candle(
                    timestamp=ts,
                    open=float(row[1]),
                    high=float(row[2]),
                    low=float(row[3]),
                    close=float(row[4]),
                    volume=float(row[5]) if len(row) > 5 else 0.0
                )
                candles.append(c)
                if len(candles) >= max_rows:
                    break
            except Exception:
                continue
    return candles


def run_backtest(csv_path: str, symbol: str = "BTCUSDT", expiry_candles: int = 5):
    print("=" * 65)
    print(f"  BACKTESTING ASSASSIN CONFLUENCE ENGINE ON {symbol}")
    print(f"  Source: {csv_path} | Expiry: {expiry_candles} candles")
    print("=" * 65)

    candles = load_candles_from_csv(csv_path)
    if not candles:
        print(f"❌ No candle data found at {csv_path}")
        return

    print(f" Loaded {len(candles):,} candles. Running simulation...")

    engine = AssassinSignalEngine(
        doji_threshold=0.10,
        fvg_min_pct=0.01,
        swing_left=2,
        swing_right=2,
        safety_tolerance_pct=0.08,
        default_expiry_seconds=expiry_candles * 60,
        require_safety_retest=True
    )

    trades = []
    n = len(candles)

    for i in range(n - expiry_candles):
        c = candles[i]
        signals = engine.update_candle(symbol, c)
        for sig in signals:
            entry_price = c.close
            future_close = candles[i + expiry_candles].close
            win = (future_close > entry_price) if sig.action == 'call' else (future_close < entry_price)
            trades.append({
                'idx': i,
                'action': sig.action,
                'pattern': sig.pattern_type,
                'trigger': sig.trigger,
                'entry': entry_price,
                'exit': future_close,
                'win': win
            })

    total_trades = len(trades)
    if total_trades == 0:
        print("No signals generated under current strict filters.")
        return

    wins = sum(1 for t in trades if t['win'])
    losses = total_trades - wins
    win_rate = (wins / total_trades) * 100.0

    print("\n" + "=" * 65)
    print(f"  BACKTEST RESULTS SUMMARY: {symbol}")
    print("=" * 65)
    print(f"  Total Trades:     {total_trades}")
    print(f"  Wins / Losses:    {wins}W / {losses}L")
    print(f"  Win Rate:         {win_rate:.2f}%")
    print("=" * 65)

    # Breakdown by pattern type
    by_pattern = {}
    for t in trades:
        pat = t['pattern']
        if pat not in by_pattern:
            by_pattern[pat] = {'wins': 0, 'total': 0}
        by_pattern[pat]['total'] += 1
        if t['win']:
            by_pattern[pat]['wins'] += 1

    print("\nBreakdown by Pattern Type:")
    for pat, stats in by_pattern.items():
        p_wr = (stats['wins'] / stats['total']) * 100.0
        print(f"  • {pat:<24}: {stats['wins']}W / {stats['total']-stats['wins']}L ({p_wr:.1f}%) [Total: {stats['total']}]")


if __name__ == "__main__":
    default_csv = "../binance_data_90d/btcusdt_1m_90d.csv"
    if not os.path.exists(default_csv):
        default_csv = glob.glob("../**/*btc*.csv", recursive=True)
        default_csv = default_csv[0] if default_csv else "btcusdt_1m_90d.csv"

    csv_file = sys.argv[1] if len(sys.argv) > 1 else default_csv
    sym = sys.argv[2] if len(sys.argv) > 2 else "BTCUSDT"
    run_backtest(csv_file, symbol=sym)
