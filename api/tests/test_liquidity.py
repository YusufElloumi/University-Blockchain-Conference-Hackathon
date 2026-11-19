"""The SIMULATED treasury's liquidity formula (liquidity.py). Pure: no database or network."""

from datetime import datetime, timedelta, timezone

import pytest

import liquidity

S = liquidity.Settings()  # defaults: 12 h grace, 0 h withdraw, 24 h safety, 15% buffer, 2% cap, 5% APY
D = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
H = timedelta(hours=1)


def event(pool=100.0, days=7.0, status="open", key="a") -> liquidity.Event:
    return liquidity.Event(key, pool, D, D + timedelta(days=days), status)


def test_before_start_contributes_nothing():
    assert liquidity.target([event()], D - H, S)["amount"] == 0


def test_between_start_and_deadline_contributes_pool_less_buffer():
    e = event()
    for t in (D, D + 3 * 24 * H, liquidity.unstake_deadline(e, S) - timedelta(seconds=1)):
        assert liquidity.target([e], t, S)["amount"] == pytest.approx(100 * 0.85)


def test_at_or_after_deadline_contributes_nothing():
    e = event()
    u = liquidity.unstake_deadline(e, S)
    assert u == e.end + 12 * H - 24 * H
    assert liquidity.target([e], u, S)["amount"] == 0
    assert liquidity.target([e], u + H, S)["amount"] == 0


@pytest.mark.parametrize("status", ["cancelled", "refunding", "refunded", "settled"])
def test_closed_events_contribute_nothing(status):
    assert liquidity.target([event(status=status)], D + H, S)["amount"] == 0


def test_liquidity_cap_applies_when_lower():
    events = [event(pool=1000, key="a"), event(pool=1000, key="b")]
    goal = liquidity.target(events, D + H, S, protocol_liquidity=50_000)  # cap = 2% of 50,000 = 1,000
    assert goal["uncapped"] == pytest.approx(1700)
    assert goal["amount"] == pytest.approx(1000) and goal["capped"]
    rows = liquidity.plan(events, D + H, S, protocol_liquidity=50_000)["events"]
    assert sum(r["allocated"] for r in rows) == pytest.approx(1000)


def test_cap_not_applied_when_higher_or_unknown():
    assert not liquidity.target([event()], D + H, S, protocol_liquidity=10**9)["capped"]
    unknown = liquidity.target([event()], D + H, S)
    assert unknown["cap"] is None and "unknown" in unknown["note"]


def test_very_short_event_earns_nothing_and_is_never_lent():
    e = event(days=0.25)  # 6 hours: U_i = start + 6 h + 12 h - 24 h, before the start
    assert liquidity.unstake_deadline(e, S) <= e.start
    assert liquidity.projected_yield(e, S) == 0
    for t in (D, D + H, D + 6 * H):
        assert not liquidity.is_eligible(e, t, S)
        assert liquidity.target([e], t, S)["amount"] == 0


def test_worked_example():
    """$100 pool, 7-day event, 12 h grace, 24 h safety, 15% buffer, 5% APY: 6.5 days lent, about $0.076."""
    e = event(pool=100, days=7)
    assert (liquidity.unstake_deadline(e, S) - e.start) / timedelta(days=1) == pytest.approx(6.5)
    assert liquidity.projected_yield(e, S) == pytest.approx(100 * 0.85 * 0.05 * 6.5 / 365)
    assert liquidity.projected_yield(e, S) == pytest.approx(0.0757, abs=1e-4)


def test_plan_rows():
    e = event()
    row = liquidity.plan([e], D + H, S)["events"][0]
    assert row["eligible"] and row["counted"]
    assert row["unstake_deadline"] == liquidity.unstake_deadline(e, S)
    assert row["allocated"] == pytest.approx(85)
    assert row["projected_yield"] == pytest.approx(liquidity.projected_yield(e, S))


def test_lead_pulls_money_back_at_the_last_run_before_the_deadline():
    e = event()
    u = liquidity.unstake_deadline(e, S)
    lead = timedelta(minutes=15)
    assert liquidity.counted(e, u - 20 * timedelta(minutes=1), S, lead)
    assert not liquidity.counted(e, u - 10 * timedelta(minutes=1), S, lead)  # next run would be too late
    assert liquidity.is_eligible(e, u - 10 * timedelta(minutes=1), S)  # still inside D..U by the formula
