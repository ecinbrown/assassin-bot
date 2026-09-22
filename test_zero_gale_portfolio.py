import os
import sys
import unittest
import json

bot_dir = r"c:\Users\DELL\Documents\anti web\assassin-bot"
sys.path.insert(0, bot_dir)

from assassin_strategy import (
    Candle,
    HybridSignalEngine,
    MultiTFCandleAggregator
)

class TestZeroGalePortfolio(unittest.TestCase):
    def test_01_zero_gale_config_integrity(self):
        config_path = os.path.join(bot_dir, "assassin_strategy", "zero_gale_setups_config.json")
        self.assertTrue(os.path.exists(config_path), "zero_gale_setups_config.json must exist")
        
        with open(config_path, "r") as f:
            setups = json.load(f)
            
        self.assertEqual(len(setups), 80, "Must have exactly 80 verified Zero-Gale setups")
        pairs = {s["pair"] for s in setups}
        self.assertEqual(pairs, {"BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"}, "Must cover all 4 major assets")
        
        for s in setups:
            self.assertGreaterEqual(s["wr"], 58.0, f"Setup {s['desc']} full WR below 58%")
            self.assertGreaterEqual(s["oos_wr"], 57.0, f"Setup {s['desc']} OOS WR below 57%")

    def test_02_engine_loader(self):
        config_path = os.path.join(bot_dir, "assassin_strategy", "zero_gale_setups_config.json")
        engine = HybridSignalEngine(config_path=config_path)
        self.assertEqual(len(engine.setups), 80)
        self.assertEqual(engine.aggregator.timeframes, [1, 3, 5, 15])

    def test_03_flat_compounding_math(self):
        # In Zero-Gale mode, payout on 85% with 62.94% OOS win rate
        win_rate = 0.6294
        payout = 0.85
        stake = 10.0
        
        ev_per_trade = (win_rate * stake * payout) - ((1.0 - win_rate) * stake)
        self.assertGreater(ev_per_trade, 0.0, "Expected value per trade must be positive")
        self.assertAlmostEqual(ev_per_trade, 1.6439, places=2)

if __name__ == "__main__":
    unittest.main()
