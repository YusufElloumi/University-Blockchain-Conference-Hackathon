"""The SIMULATED treasury job (yieldsim.py) and its admin routes. No network, no real funds."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import config
import db
import liquidity
import yieldsim
from test_stage4 import challenge, client, fakes, make_token, state  # noqa: F401


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as s:
        yield s


def add_event(session, address, start, days=7.0, pool_usdc=100, players=2, status="open"):
    session.add(db.Challenge(address=address, name=address, buy_in_units=10**6, start_time=start,
                             end_time=start + timedelta(days=days), status=status, invite_code=address[:6]))
    session.add(db.ChainEvent(signature="sig-" + address, event_index=0, name="PlayerJoined", challenge=address,
                              slot=1, data=json.dumps({"pool_total": pool_usdc * 10**6, "player_count": players})))
    session.commit()


def test_lends_then_pulls_back_before_the_deadline(session):
    now = datetime.now(timezone.utc)
    add_event(session, "EventA" + "1" * 38, now - timedelta(hours=1))
    yieldsim.rebalance(session)
    position = session.get(db.SimPosition, 1)
    assert position.principal == pytest.approx(85)
    deadline = now - timedelta(hours=1) + timedelta(days=7) - timedelta(hours=12)
    hours_left = (deadline - now) / timedelta(hours=1)
    yieldsim.advance(session, hours_left - 0.1)  # just before U_i: already pulled back by the last run
    assert position.principal == 0
    assert position.interest > 0
    logs = session.scalars(select(db.SimLog)).all()
    assert any(r.action == "withdraw" and "Pulled back" in r.reason for r in logs)
    assert not any(r.warning for r in logs)
    view = yieldsim.view(session)
    assert view["simulated"] and view["events"][0]["status"] == "returned"
    assert view["total_escrowed"] == pytest.approx(100) and view["lent"] == 0


def test_interest_matches_the_formula_and_never_touches_the_pool(session):
    now = datetime.now(timezone.utc)
    add_event(session, "EventB" + "1" * 38, now - timedelta(hours=1), days=30)
    yieldsim.rebalance(session)
    yieldsim.advance(session, 24)
    position = session.get(db.SimPosition, 1)
    # 85 USDC for one day at 5%, compounding every 15 minutes: very close to simple interest.
    assert position.interest == pytest.approx(85 * 0.05 / 365, rel=1e-3)
    assert position.principal == pytest.approx(85)  # principal stays at target; interest kept apart
    assert yieldsim.load_events(session)[0].pool == pytest.approx(100)


def test_warns_when_an_event_passed_its_deadline_while_lent(session):
    now = datetime.now(timezone.utc)
    add_event(session, "EventC" + "1" * 38, now - timedelta(hours=1), days=2)  # U_i = start + 36 h
    yieldsim.rebalance(session)
    position = session.get(db.SimPosition, 1)
    position.clock_offset_seconds = 3 * 24 * 3600  # jump past U_i without the in-between runs
    session.commit()
    yieldsim.rebalance(session)
    last = session.scalars(select(db.SimLog).order_by(db.SimLog.id.desc())).first()
    assert last.warning and "deadline" in last.warning
    assert position.principal == 0


def test_closed_and_underfilled_events_are_not_lent(session):
    now = datetime.now(timezone.utc)
    add_event(session, "Settled" + "1" * 37, now - timedelta(hours=1), status="settled")
    add_event(session, "OnePlayer" + "1" * 35, now - timedelta(hours=1), players=1)
    add_event(session, "Future" + "1" * 38, now + timedelta(days=1))
    statuses = {e.key[:6]: e.status for e in yieldsim.load_events(session)}
    assert statuses["OnePla"] == "refunding"
    yieldsim.rebalance(session)
    assert session.get(db.SimPosition, 1).principal == 0
    assert {e["status"] for e in yieldsim.view(session)["events"]} == {"settled", "refunding", "not yet started"}


def test_tick_rebalances_at_most_every_15_minutes(session):
    add_event(session, "EventD" + "1" * 38, datetime.now(timezone.utc) - timedelta(hours=1))
    assert yieldsim.rebalance_if_due(session)
    assert not yieldsim.rebalance_if_due(session)


def test_fallback_rate_is_labelled(monkeypatch):
    monkeypatch.setattr(config, "SIM_LIVE_RATE", False)
    monkeypatch.setitem(yieldsim._rate_cache, "value", None)
    r = yieldsim.rate()
    assert r["apy"] == config.SIM_APY and not r["live"] and r["source"] == "using fallback rate"


def test_reset(session):
    add_event(session, "EventE" + "1" * 38, datetime.now(timezone.utc) - timedelta(hours=1))
    yieldsim.advance(session, 5)
    yieldsim.reset(session)
    position = session.get(db.SimPosition, 1)
    assert position.principal == 0 and position.interest == 0 and position.clock_offset_seconds == 0


def test_settings_defaults():
    assert yieldsim.settings() == liquidity.Settings()


def test_admin_routes(monkeypatch, client, challenge):  # noqa: F811  (fixtures from test_stage4)
    headers = make_token("maya")
    assert client.get("/admin/treasury", headers=headers).status_code == 403
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"maya@example.com"})
    reply = client.post("/admin/treasury/rebalance", headers=headers)
    assert reply.status_code == 200 and reply.json()["simulated"] is True
    reply = client.post("/admin/treasury/clock", json={"advance_hours": 6}, headers=headers)
    assert reply.status_code == 200 and reply.json()["clock_offset_hours"] == 6
    assert client.post("/admin/treasury/clock", json={"reset": True}, headers=headers).json()["clock_offset_hours"] == 0
