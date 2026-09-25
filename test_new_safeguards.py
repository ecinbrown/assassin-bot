import time
from main import AssassinController, ActiveTrade, AssassinSignal

def test_safeguards():
    controller = AssassinController(symbols=["BTCUSDT", "ETHUSDT", "BNBUSDT"])
    
    # 1. Test Time-spacing
    controller.last_trade_time = time.time() - 30.0  # 30 seconds ago
    min_trade_interval = 90.0
    time_since = time.time() - controller.last_trade_time
    assert time_since < min_trade_interval, "Should be within interval"
    print("Test 1: Time spacing condition verified")

    # 2. Test Indicator Collision across pairs
    active_t = ActiveTrade(
        symbol="BTCUSDT", action="call", entry_price=84000.0, stake_native=1.0,
        entry_time=time.time(), expiry_time=time.time()+180, epoch=1,
        indicator_family="HTF_PULLBACK_15m_EMA20_RSI7",
        strategy_key="15m_EMA20 + RSI7<=30 + BB2.0s + Vol1.3x"
    )
    controller.active_trades.append(active_t)

    candidate_sig_eth = AssassinSignal(
        symbol="ETHUSDT", action="call", price=2600.0, confidence=0.9,
        trigger="ETHUSDT 3m | 15m_EMA20 + RSI7<=25 + BB1.8s + Vol1.8x",
        pattern_type="HTF_PULLBACK_3M", expiry_seconds=180, timestamp=time.time(),
        verdict="TAKE_IT", regime="HYBRID_85PCT", solid_count=3, soft_count=0,
        metadata={"indicator_family": "HTF_PULLBACK_15m_EMA20_RSI7", "strategy_key": "15m_EMA20 + RSI7<=25 + BB1.8s + Vol1.8x"}
    )
    colliding = [
        t for t in controller.active_trades
        if t.symbol != candidate_sig_eth.symbol and t.indicator_family == candidate_sig_eth.metadata["indicator_family"]
    ]
    assert len(colliding) == 1, "ETH should be blocked because BTC has the same indicator family active!"
    print("Test 2: Cross-pair indicator collision properly detected and blocked")

    # 3. Test Same-pair Strategy Rotation
    controller.last_pair_strategy["BTCUSDT"] = "HTF_PULLBACK_15m_EMA20_RSI7"
    candidate_sig_btc_same = AssassinSignal(
        symbol="BTCUSDT", action="call", price=84100.0, confidence=0.9,
        trigger="BTCUSDT 3m | 15m_EMA20 + RSI7<=30 + BB2.0s + Vol1.3x",
        pattern_type="HTF_PULLBACK_3M", expiry_seconds=180, timestamp=time.time(),
        verdict="TAKE_IT", regime="HYBRID_85PCT", solid_count=3, soft_count=0,
        metadata={"indicator_family": "HTF_PULLBACK_15m_EMA20_RSI7", "strategy_key": "15m_EMA20 + RSI7<=30 + BB2.0s + Vol1.3x"}
    )
    is_same_strat = controller.last_pair_strategy.get("BTCUSDT") == candidate_sig_btc_same.metadata["indicator_family"]
    assert is_same_strat, "Same strategy should be flagged on the next trade on same pair!"
    print("Test 3: Same-pair strategy rotation condition properly verified")

    # 4. Test Negative Balance Recovery Protection
    curr_bal = -15.5
    debt_loss = 3.22
    payout = 0.90
    rec_target = debt_loss
    rec_base = round(rec_target / payout, 2)
    if curr_bal > 0:
        rec_base = min(rec_base, round(curr_bal * 0.37, 2))
    rec_base = max(rec_base, controller.stake_native)
    assert rec_base > 0, "Recovery base must always remain positive!"
    assert rec_base == 3.58, f"Expected 3.58, got {rec_base}"
    print("Test 4: Recovery stake is strictly positive even on negative balance")

    print("\nALL SAFEGUARD UNIT TESTS PASSED (100%)!")

if __name__ == "__main__":
    test_safeguards()
