import os
import sys
import unittest
import numpy as np

# Ensure local assassin_strategy can be imported
sys.path.insert(0, os.path.dirname(__file__))

from assassin_strategy import (
    Candle,
    HybridSignalEngine,
    MultiTFCandleAggregator
)
from main import AssassinController


class TestHybridDeployment(unittest.TestCase):
    def test_01_config_integrity(self):
        engine = HybridSignalEngine()
        self.assertEqual(len(engine.setups), 281, "Must have exactly 281 verified BTC+ETH setups")
        pairs = {s.pair for s in engine.setups}
        self.assertEqual(pairs, {"BTCUSDT", "ETHUSDT"}, "Must cover BTC and ETH alone")
        for s in engine.setups:
            self.assertGreaterEqual(s.wr, 84.8, f"Setup {s.desc} win rate below target")

    def test_02_candle_aggregator(self):
        agg = MultiTFCandleAggregator(timeframes=[1, 3, 5])
        # Stream 5 1m candles
        for i in range(1, 6):
            c = Candle(
                timestamp=1700000000 + i * 60,
                open=100.0 + i,
                high=105.0 + i,
                low=95.0 + i,
                close=102.0 + i,
                volume=100.0,
                trades=10.0
            )
            closed = agg.update_1m_candle("BTCUSDT", c)
            closed_tfs = [x[0] for x in closed]
            self.assertIn(1, closed_tfs, "1m should always close")
            if i == 3:
                self.assertIn(3, closed_tfs, "3m bar should close on 3rd candle")
            if i == 5:
                self.assertIn(5, closed_tfs, "5m bar should close on 5th candle")

    def test_03_6pct_compounding(self):
        controller = AssassinController(symbols=["BTCUSDT"], stake_native=0.01)
        
        # Test $20 starting balance -> 6.1% is $1.22
        stake_20 = controller.calculate_dynamic_stake(20.0, "BTCUSDT")
        self.assertEqual(stake_20, 1.22, "At $20 balance, 6.1% is $1.22")
        
        # Test $10 starting balance -> floor $1.00 (since 6.1% is 0.61)
        stake_10 = controller.calculate_dynamic_stake(10.0, "BTCUSDT")
        self.assertEqual(stake_10, 1.00, "At $10 balance, floor must be $1.00")

        # Test $50 balance -> $3.05 base stake
        stake_50 = controller.calculate_dynamic_stake(50.0, "BTCUSDT")
        self.assertEqual(stake_50, 3.05, "At $50 balance, 6.1% is $3.05")

        # Test $100 balance -> $6.10 base stake
        stake_100 = controller.calculate_dynamic_stake(100.0, "BTCUSDT")
        self.assertEqual(stake_100, 6.10, "At $100 balance, 6.1% is $6.10")


    def test_04_signal_evaluation_pipeline(self):
        engine = HybridSignalEngine()
        # Pre-seed ETH 4m with 60 bars
        candles = []
        for i in range(60):
            candles.append(Candle(
                timestamp=1700000000 + i * 240,
                open=3000.0,
                high=3010.0,
                low=2990.0,
                close=3000.0,
                volume=500.0,
                trades=50.0
            ))
        engine.preload_history("ETHUSDT", 4, candles)
        self.assertEqual(len(engine.aggregator.history[("ETHUSDT", 4)]), 60)



if __name__ == "__main__":
    unittest.main()
