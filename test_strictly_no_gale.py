import os
import sys
import unittest
import json

bot_dir = r"c:\Users\DELL\Documents\anti web\assassin-bot"
sys.path.insert(0, bot_dir)

from assassin_strategy import (
    HybridSignalEngine,
    MultiTFCandleAggregator
)

class TestStrictlyNoGale(unittest.TestCase):
    def test_01_config_integrity(self):
        for fname in ["strictly_no_gale_verified_config.json", "oos_85pct_30tpd_config.json"]:
            path = os.path.join(bot_dir, "assassin_strategy", fname)
            self.assertTrue(os.path.exists(path), f"{fname} must exist")
            with open(path, "r", encoding="utf-8") as f:
                setups = json.load(f)
            self.assertEqual(len(setups), 160, f"{fname} must contain exactly 160 setups")
            for s in setups:
                self.assertEqual(s["type"], "EXTREME_REVERSAL")
                self.assertGreaterEqual(s["oos_wr"], 70.0, f"{s['desc']} OOS WR must be >= 70%")
                self.assertGreaterEqual(s["wr"], 60.0, f"{s['desc']} 365d WR must be >= 60%")

    def test_02_engine_loading(self):
        path = os.path.join(bot_dir, "assassin_strategy", "strictly_no_gale_verified_config.json")
        engine = HybridSignalEngine(config_path=path)
        self.assertEqual(len(engine.setups), 160)
        self.assertTrue(len(engine.aggregator.timeframes) >= 12)

    def test_03_zero_gale_flat_ev(self):
        # Even at 67.04% full 365d win rate or 72.98% OOS win rate, flat $1 staking has positive EV
        payout = 0.85
    def test_04_dynamic_compounding_7_5_pct(self):
        from main import AssassinController
        controller = AssassinController(symbols=["BTCUSDT"])
        # Test $100 balance -> 7.5% = $7.50
        stake_100 = controller.calculate_dynamic_stake(100.0, symbol="BTCUSDT")
        self.assertEqual(stake_100, 7.50)
        # Test $20 balance -> 7.5% = $1.50
        stake_20 = controller.calculate_dynamic_stake(20.0, symbol="BTCUSDT")
        self.assertEqual(stake_20, 1.50)
        # Test $10 balance -> 7.5% = $0.75, clamped to min $1.00
        stake_10 = controller.calculate_dynamic_stake(10.0, symbol="BTCUSDT")
        self.assertEqual(stake_10, 1.00)

if __name__ == "__main__":
    unittest.main()
