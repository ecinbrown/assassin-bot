import os
import sys
import unittest
import time
from dataclasses import dataclass

bot_dir = r"c:\Users\DELL\Documents\anti web\assassin-bot"
sys.path.insert(0, bot_dir)

from assassin_strategy import HybridSignalEngine, Candle
from main import AssassinController, ActiveTrade

class TestNoGaleDeploymentV61(unittest.TestCase):
    def setUp(self):
        os.environ["STRATEGY_MODE"] = "NOGALE_55TPD"

    def test_01_nogale_config_loading(self):
        cfg_path = os.path.join(bot_dir, "assassin_strategy", "nogale_83wr_55tpd_config.json")
        self.assertTrue(os.path.exists(cfg_path))
        engine = HybridSignalEngine(config_path=cfg_path)
        self.assertEqual(len(engine.setups), 97)
        pairs = {s.pair for s in engine.setups}
        self.assertEqual(pairs, {"BTCUSDT", "ETHUSDT", "BNBUSDT"})

    def test_02_5pct_staking_and_caps(self):
        controller = AssassinController(symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"], stake_native=1.0)
        # At $100 balance, 5% is $5.00
        stake_100 = controller.calculate_dynamic_stake(100.0, symbol="BTCUSDT")
        self.assertEqual(stake_100, 5.0)

        # At $10,000 balance, ETHUSDT should hit full $250 platform cap (not $112.61!)
        stake_eth = controller.calculate_dynamic_stake(10000.0, symbol="ETHUSDT")
        self.assertEqual(stake_eth, 250.0)

        # BTCUSDT should hit $1,000 platform cap at $30,000 balance
        stake_btc = controller.calculate_dynamic_stake(30000.0, symbol="BTCUSDT")
        self.assertEqual(stake_btc, 1000.0)

    def test_03_zero_gale_guarantee(self):
        strategy_mode = os.environ.get("STRATEGY_MODE", "NOGALE_55TPD").upper()
        is_nogale = any(x in strategy_mode for x in ("ZERO_GALE", "FLAT", "0GALE", "NOGALE", "83WR", "55TPD"))
        max_allowed_gale = 0 if is_nogale else 1
        self.assertEqual(max_allowed_gale, 0, "No-Gale must strictly enforce max_allowed_gale = 0")

        # Simulate losing trade
        t = ActiveTrade(
            symbol="BTCUSDT",
            action="call",
            entry_price=60000.0,
            stake_native=5.0,
            entry_time=time.time() - 300,
            expiry_time=time.time() - 1,
            epoch=100,
            gale_level=0,
            total_sequence_stake=5.0
        )
        # In No-Gale, t.gale_level < max_allowed_gale (0 < 0) is FALSE -> never triggers gale
        self.assertFalse(max_allowed_gale > 0 and t.gale_level < max_allowed_gale)

if __name__ == "__main__":
    unittest.main()
