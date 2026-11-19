"""Liquidity scheduling for the SIMULATED treasury: how much escrowed USDC could be lent out, and when.

SIMULATION ONLY. Nothing here moves money. The real buy-ins stay in the Solana program's vault; this module
only answers "if we were lending, how much would be out right now, and what would it earn?". It is pure
(no database, network or clock), so it is easy to test and to explain. `yieldsim.py` feeds it and stores
the pretend position.

The idea, per event i:

    P_i  pool size: every buy-in in the event, in USDC
    D_i  start time: joining closes. Before this a player can still be refunded, so we never lend it.
    E_i  end time
    S_i = E_i + GRACE_HOURS                       payout must be possible by here (late fitness syncs)
    U_i = S_i - WITHDRAW_HOURS - SAFETY_HOURS     the money must be back from the lender by here

An event is "eligible to lend" at time t when D_i <= t < U_i and it is still running normally (not
settled, refunded, or about to be refunded). Its money is out only inside that window.

    Target(t) = (1 - BUFFER_PCT) * sum of P_i over eligible events
    Target(t) = min(Target(t), LIQUIDITY_CAP_PCT * protocol's available USDC)   (only if that is known)

The buffer keeps some money liquid even inside the window. The cap stops us from being a big share of the
lending market, where we could struggle to get our money out.

    Yield_i = P_i * (1 - BUFFER_PCT) * APY * (U_i - D_i in days) / 365     (zero when U_i <= D_i)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

HOUR = timedelta(hours=1)

# Event statuses where the money is going (or has gone) back to players or winners: never lent.
CLOSED_STATUSES = {"settled", "refunded", "refunding", "cancelled"}


@dataclass(frozen=True)
class Settings:
    grace_hours: float = 12  # wait after the end for late fitness syncs before paying out
    withdraw_hours: float = 0  # how long the lending protocol takes to hand money back
    safety_hours: float = 24  # extra margin before payout
    buffer_pct: float = 0.15  # share of eligible money that is never lent
    liquidity_cap_pct: float = 0.02  # we never hold more than this share of the protocol's available USDC
    apy: float = 0.05  # fallback yearly yield rate (0.05 = 5%)


@dataclass(frozen=True)
class Event:
    """What the formula needs about one event. `pool` is in USDC (not the smallest unit)."""

    key: str  # the challenge address
    pool: float
    start: datetime  # D_i
    end: datetime  # E_i
    status: str  # open, settled, refunded, refunding, cancelled


def payout_deadline(event: Event, s: Settings) -> datetime:
    """S_i: the latest time a payout could be due."""
    return event.end + s.grace_hours * HOUR


def unstake_deadline(event: Event, s: Settings) -> datetime:
    """U_i: the money must be back from the lender by this time."""
    return payout_deadline(event, s) - (s.withdraw_hours + s.safety_hours) * HOUR


def is_eligible(event: Event, t: datetime, s: Settings) -> bool:
    """True when this event's money may be out on loan at time t."""
    if event.status in CLOSED_STATUSES:
        return False
    return event.start <= t < unstake_deadline(event, s)


def projected_yield(event: Event, s: Settings, apy: float | None = None) -> float:
    """What this event's lent money would earn over its whole window D_i to U_i (simple interest)."""
    days = (unstake_deadline(event, s) - event.start) / timedelta(days=1)
    if days <= 0:  # a very short event: never lent, so it earns nothing
        return 0.0
    rate = s.apy if apy is None else apy
    return event.pool * (1 - s.buffer_pct) * rate * days / 365


def counted(event: Event, t: datetime, s: Settings, lead: timedelta = timedelta(0)) -> bool:
    """Whether a job running at t should hold this event's money until its next run.

    With `lead` = the time until the next run, money comes back at the last run BEFORE U_i rather than
    the first run after it. lead = 0 is exactly `is_eligible`.
    """
    return is_eligible(event, t, s) and t + lead < unstake_deadline(event, s)


def target(events: list[Event], t: datetime, s: Settings, protocol_liquidity: float | None = None,
           lead: timedelta = timedelta(0)) -> dict:
    """How much should be lent at time t. Returns the amount and how it was reached.

    `protocol_liquidity` is the lending protocol's available USDC; None means unknown, and then the cap
    is skipped (the result says so). `lead`: see `counted`.
    """
    uncapped = (1 - s.buffer_pct) * sum(e.pool for e in events if counted(e, t, s, lead))
    if protocol_liquidity is None:
        return {"amount": uncapped, "uncapped": uncapped, "cap": None, "capped": False,
                "note": "Protocol liquidity unknown, so the liquidity cap was not applied."}
    cap = s.liquidity_cap_pct * protocol_liquidity
    return {"amount": min(uncapped, cap), "uncapped": uncapped, "cap": cap, "capped": cap < uncapped,
            "note": "Liquidity cap applied." if cap < uncapped else "Under the liquidity cap."}


def plan(events: list[Event], t: datetime, s: Settings, protocol_liquidity: float | None = None,
         apy: float | None = None, lead: timedelta = timedelta(0)) -> dict:
    """Everything the panel and the job need: the target, and a row per event.

    Each row: eligible yes/no, U_i, amount allocated (its share of the target; if the cap cuts the total,
    every eligible event is scaled down by the same factor), and projected yield over its window.
    """
    goal = target(events, t, s, protocol_liquidity, lead)
    scale = goal["amount"] / goal["uncapped"] if goal["uncapped"] > 0 else 0.0
    rows = []
    for e in events:
        eligible = is_eligible(e, t, s)
        held = counted(e, t, s, lead)
        rows.append({
            "key": e.key,
            "eligible": eligible,
            "counted": held,  # money out on (simulated) loan after this run
            "unstake_deadline": unstake_deadline(e, s),
            "allocated": e.pool * (1 - s.buffer_pct) * scale if held else 0.0,
            "projected_yield": projected_yield(e, s, apy),
        })
    return {"target": goal, "events": rows}
