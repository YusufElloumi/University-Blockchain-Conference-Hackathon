"""The SIMULATED treasury: one pretend lending position for all events. No real funds are lent or moved.

Each run (every 15 minutes from /internal/tick, or on demand from the admin Treasury panel):
  1. accrues interest on the position since its last update, at the current APY (interest is part of the
     position, so it compounds run by run),
  2. works out Target(t) with `liquidity.py`,
  3. pretends to deposit or withdraw the difference so principal = Target(t),
  4. writes a `sim_log` row.

Reads only our database (and, optionally, Jupiter Lend's public rate). Never calls the Solana program, never
changes a challenge, and never touches settlement: interest is stored on its own and is never added to any
event's pool or payout.

The demo time control (`advance`) shifts only this module's clock (`clock_offset_seconds`). Real events,
scoring and settlement keep using real time.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

import config
import db
import liquidity

log = logging.getLogger("loser_buys")

RUN_EVERY = timedelta(minutes=config.SIM_REBALANCE_MINUTES)
MAX_ADVANCE = timedelta(days=60)
YEAR = timedelta(days=365)
USDC = 10**config.USDC_DECIMALS


def settings() -> liquidity.Settings:
    return liquidity.Settings(
        grace_hours=config.SIM_GRACE_HOURS, withdraw_hours=config.SIM_WITHDRAW_HOURS,
        safety_hours=config.SIM_SAFETY_HOURS, buffer_pct=config.SIM_BUFFER_PCT,
        liquidity_cap_pct=config.SIM_LIQUIDITY_CAP_PCT, apy=config.SIM_APY,
    )


# ---------- live rate (Jupiter Lend Earn, read only) ----------

_rate_cache: dict = {"at": 0.0, "value": None}
RATE_TTL_SECONDS = 15 * 60


def _fetch_jupiter() -> dict:
    """USDC's supply rate and withdrawable liquidity from Jupiter Lend Earn (mainnet; read only).

    `supplyRate` is in 1e4 units of a percent fraction: "475" means 4.75%. Amounts are in USDC's smallest
    unit (6 decimals). `liquiditySupplyData.withdrawable` is what could be taken out right now.
    """
    headers = {"x-api-key": config.JUPITER_API_KEY} if config.JUPITER_API_KEY else {}
    response = httpx.get(config.JUPITER_LEND_TOKENS_URL, headers=headers, timeout=8)
    response.raise_for_status()
    for token in response.json():
        asset = token.get("asset") or {}
        if asset.get("symbol") == "USDC":
            decimals = int(asset.get("decimals") or 6)
            withdrawable = (token.get("liquiditySupplyData") or {}).get("withdrawable")
            return {
                "apy": int(token["supplyRate"]) / 10_000,
                "liquidity": int(withdrawable) / 10**decimals if withdrawable is not None else None,
            }
    raise ValueError("No USDC token in Jupiter Lend Earn's list")


def rate() -> dict:
    """The APY to use and where it came from, cached for 15 minutes. Any failure falls back to config.APY."""
    now = time.monotonic()
    if _rate_cache["value"] is None or now - _rate_cache["at"] > RATE_TTL_SECONDS:
        try:
            if not config.SIM_LIVE_RATE:
                raise RuntimeError("live rate turned off (SIM_LIVE_RATE=0)")
            live = _fetch_jupiter()
            value = {"apy": live["apy"], "liquidity": live["liquidity"], "live": True,
                     "source": "Jupiter Lend Earn USDC supply rate (mainnet, read only)"}
        except Exception as e:  # network, rate limit, changed format: never break the panel or the job
            log.warning("Jupiter Lend rate unavailable, using fallback rate: %s", e)
            value = {"apy": config.SIM_APY, "liquidity": None, "live": False, "source": "using fallback rate"}
        _rate_cache.update(at=now, value=value)
    return _rate_cache["value"]


# ---------- events and position ----------


def load_events(session: Session) -> list[liquidity.Event]:
    """Every challenge as the formula sees it. Pool = the program's latest pool total from the Stream,
    or buy-in x recorded players if no event has arrived. An open challenge past its start with fewer
    than 2 players is about to be refunded, so it counts as "refunding"."""
    pools: dict[str, tuple[int, int]] = {}
    for row in session.scalars(select(db.ChainEvent).where(db.ChainEvent.name == "PlayerJoined")
                               .order_by(db.ChainEvent.slot, db.ChainEvent.id)):
        data = json.loads(row.data)
        pools[row.challenge] = (int(data["pool_total"]), int(data["player_count"]))
    players = dict(session.execute(select(db.Participant.challenge_id, func.count())
                                   .group_by(db.Participant.challenge_id)).all())
    now = datetime.now(timezone.utc)  # real time: "refunding" is a real-world fact, not a simulated one
    out = []
    for c in session.scalars(select(db.Challenge)):
        pool_units, count = pools.get(c.address, (c.buy_in_units * players.get(c.id, 0), players.get(c.id, 0)))
        status = c.status
        start = db.utc(c.start_time)
        if status == "open" and now >= start and count < 2:
            status = "refunding"
        out.append(liquidity.Event(c.address, pool_units / USDC, start, db.utc(c.end_time), status))
    return out


def _position(session: Session) -> db.SimPosition:
    position = session.get(db.SimPosition, 1)
    if position is None:
        position = db.SimPosition(id=1, principal=0.0, interest=0.0, clock_offset_seconds=0)
        session.add(position)
        session.flush()
    return position


def sim_now(position: db.SimPosition) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=position.clock_offset_seconds or 0)


def _step(session: Session, position: db.SimPosition, events: list[liquidity.Event], t: datetime,
          rate_now: dict, always_log: bool = True) -> None:
    """One rebalance at simulated time t."""
    s = settings()
    # 1. Interest since the last run, on everything in the position (so it compounds per run).
    earned = 0.0
    if position.updated_at is not None:
        years = (t - db.utc(position.updated_at)) / YEAR
        if years > 0:
            earned = (position.principal + position.interest) * rate_now["apy"] * years
            position.interest += earned
    # 2. Target. Money for an event comes back at the last run before its deadline (lead = one interval).
    result = liquidity.plan(events, t, s, rate_now["liquidity"], rate_now["apy"], lead=RUN_EVERY)
    goal = result["target"]["amount"]
    # Warning: an event counted last run that is now at or past its deadline was lent too long.
    before = set(json.loads(position.counted or "[]"))
    by_key = {e.key: e for e in events}
    late = [k for k in before if k in by_key and t >= liquidity.unstake_deadline(by_key[k], s)]
    warning = None
    if late:
        warning = ("Past the money-back deadline while still lent: " + ", ".join(k[:6] + "..." for k in late)
                   + ". Its money should already have been pulled back.")
        log.warning("Simulated treasury: %s", warning)
    # 3. Deposit or withdraw the difference.
    diff = goal - position.principal
    action = "deposit" if diff > 1e-9 else "withdraw" if diff < -1e-9 else "hold"
    position.principal = goal
    now_counted = [r["key"] for r in result["events"] if r["counted"]]
    position.counted = json.dumps(now_counted)
    position.updated_at = t
    # 4. Log.
    if always_log or action != "hold" or warning:
        reason = f"{len(now_counted)} event(s) lending. {result['target']['note']}"
        joined = set(now_counted)
        if action == "withdraw":
            back = sorted(before - joined)
            if back:
                reason = "Pulled back before the deadline: " + ", ".join(k[:6] + "..." for k in back) + ". " + reason
        session.add(db.SimLog(sim_time=t, action=action, amount=abs(diff), principal=goal,
                              interest_added=earned, reason=reason, warning=warning))


def rebalance(session: Session) -> None:
    """One run now (simulated time)."""
    position = _position(session)
    _step(session, position, load_events(session), sim_now(position), rate())
    session.commit()


def rebalance_if_due(session: Session) -> bool:
    """For /internal/tick: runs only if 15 minutes have passed since the last run."""
    position = _position(session)
    if position.updated_at is not None and sim_now(position) - db.utc(position.updated_at) < RUN_EVERY:
        session.rollback()
        return False
    rebalance(session)
    return True


def advance(session: Session, hours: float) -> None:
    """Demo time control: moves the SIMULATED clock forward and runs the job every 15 simulated minutes on
    the way, as the scheduler would have. Only runs that change something are logged. Real events are not
    affected."""
    span = timedelta(hours=hours)
    if not timedelta(0) < span <= MAX_ADVANCE:
        raise ValueError("Advance by more than 0 and at most 60 days.")
    position = _position(session)
    events = load_events(session)
    rate_now = rate()
    start = sim_now(position)
    if position.updated_at is None:
        _step(session, position, events, start, rate_now)
    t, end = start, start + span
    while t + RUN_EVERY < end:
        t += RUN_EVERY
        _step(session, position, events, t, rate_now, always_log=False)
    position.clock_offset_seconds = (position.clock_offset_seconds or 0) + int(span.total_seconds())
    _step(session, position, events, sim_now(position), rate_now)
    session.commit()


def reset(session: Session) -> None:
    """Back to real time with an empty position. The log is kept, with a reset row."""
    position = _position(session)
    position.principal = position.interest = 0.0
    position.clock_offset_seconds = 0
    position.updated_at = None
    position.counted = None
    session.add(db.SimLog(sim_time=datetime.now(timezone.utc), action="reset", amount=0.0, principal=0.0,
                          reason="Simulation reset to real time; position emptied."))
    session.commit()


# ---------- what the panel shows ----------


def _status(row: dict, event: liquidity.Event, t: datetime) -> str:
    if event.status in liquidity.CLOSED_STATUSES:
        return event.status
    if t < event.start:
        return "not yet started"
    return "lending" if row["counted"] else "returned"


def view(session: Session) -> dict:
    position = _position(session)
    session.commit()
    t = sim_now(position)
    s = settings()
    rate_now = rate()
    events = load_events(session)
    result = liquidity.plan(events, t, s, rate_now["liquidity"], rate_now["apy"], lead=RUN_EVERY)
    rows = {r["key"]: r for r in result["events"]}
    names = dict(session.execute(select(db.Challenge.address, db.Challenge.name)).all())
    escrowed = sum(e.pool for e in events if e.status not in liquidity.CLOSED_STATUSES)
    # Active = still holding money, or finished within the last week of simulated time.
    active = [e for e in events if e.status not in liquidity.CLOSED_STATUSES or t - e.end < timedelta(days=7)]
    active.sort(key=lambda e: e.start)
    logs = session.scalars(select(db.SimLog).order_by(db.SimLog.id.desc()).limit(20)).all()
    return {
        "simulated": True,
        "sim_time": t.isoformat(),
        "real_time": datetime.now(timezone.utc).isoformat(),
        "clock_offset_hours": (position.clock_offset_seconds or 0) / 3600,
        "last_run": db.utc(position.updated_at).isoformat() if position.updated_at else None,
        "total_escrowed": escrowed,
        "lent": position.principal,
        "liquid_buffer": max(escrowed - position.principal, 0.0),
        "interest": position.interest,
        "target_now": result["target"],
        "apy": rate_now["apy"],
        "apy_source": rate_now["source"],
        "apy_live": rate_now["live"],
        "protocol_liquidity": rate_now["liquidity"],
        "settings": s.__dict__,
        "events": [
            {"address": e.key, "name": names.get(e.key, ""), "pool": e.pool, "start": e.start.isoformat(),
             "end": e.end.isoformat(), "unstake_deadline": rows[e.key]["unstake_deadline"].isoformat(),
             "status": _status(rows[e.key], e, t), "allocated": rows[e.key]["allocated"],
             # A refunded (or about to be refunded) event's money goes straight back: nothing to project.
             "projected_yield": 0.0 if e.status in ("refunded", "refunding", "cancelled")
             else rows[e.key]["projected_yield"]}
            for e in active
        ],
        "log": [
            {"sim_time": db.utc(r.sim_time).isoformat(), "action": r.action, "amount": r.amount,
             "principal": r.principal, "interest_added": r.interest_added, "reason": r.reason,
             "warning": r.warning}
            for r in logs
        ],
    }
