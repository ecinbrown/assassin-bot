import asyncio, os, sys, time
sys.path.insert(0, os.path.abspath('assassin-bot'))
from assassin_strategy.hybrid_engine import HybridSignalEngine
from assassin_strategy.candle_utils import Candle
import urllib.request, json

async def main():
    cfg_path = os.path.join(os.path.dirname(__file__), "assassin_strategy", "oos_85pct_30tpd_config.json")
    engine = HybridSignalEngine(config_path=cfg_path)
    symbols = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']
    
    print("Preloading from Binance...")
    await engine.preload_from_binance(symbols, limit=1000)
    
    print("\nPreload complete. Now fetching latest 120 1m candles for each symbol and testing signal generation:")
    total_signals = 0
    for sym in symbols:
        url = f"https://api.binance.com/api/v3/klines?symbol={sym}&interval=1m&limit=120"
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        candles_data = json.loads(urllib.request.urlopen(req, timeout=10).read())
        candles = [
            Candle(
                timestamp=float(k[0])/1000.0,
                open=float(k[1]), high=float(k[2]), low=float(k[3]), close=float(k[4]),
                volume=float(k[5]), trades=float(k[8]) if len(k) > 8 else 1.0
            )
            for k in candles_data
        ]
        
        sym_signals = []
        for c in candles:
            closed = engine.aggregator.update_1m_candle(sym, c)
            for tf, tf_c in closed:
                sigs = engine.evaluate_setups(sym, tf, tf_c)
                if sigs:
                    sym_signals.extend(sigs)
        print(f"  {sym}: {len(sym_signals)} signals in the last 120 minutes (2 hours)")
        total_signals += len(sym_signals)
        for s in sym_signals[:5]:
            print(f"    -> [{s['setup'].tf}m] {s['action'].upper()} | {s['trigger'][:80]} | WR: {s['setup'].wr:.1f}%")

    print(f"\nTOTAL SIGNALS in last 2 hours: {total_signals}")

if __name__ == "__main__":
    asyncio.run(main())
