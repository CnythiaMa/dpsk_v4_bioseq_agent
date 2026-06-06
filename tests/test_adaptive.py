from dpsk_v4_bioseq_agent.adaptive import AdaptiveLimiter


def test_throttle_halves_then_clamps_to_lo():
    lim = AdaptiveLimiter(init=10, lo=3, hi=20)
    lim.on_throttle()
    assert lim.limit == 5          # 10 -> 10//2
    for _ in range(5):
        lim.on_throttle()
    assert lim.limit == 3          # clamped at lo


def test_success_run_increases_within_hi():
    lim = AdaptiveLimiter(init=4, lo=3, hi=8, increase_after=4, cooldown_s=0.0)
    start = lim.limit
    for _ in range(100):
        lim.on_success()
    assert start < lim.limit <= 8  # additive increase, capped at hi


def test_snapshot_has_expected_keys():
    snap = AdaptiveLimiter().snapshot()
    assert {"limit", "active", "throttles", "calls"} <= set(snap)
