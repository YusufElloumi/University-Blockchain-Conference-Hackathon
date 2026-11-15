"""Turns a player's activities into stored points, and builds the leaderboard.

`score_entries` holds points and activity IDs only. Activity details stay with the fitness provider
and are only ever shown to their owner.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db
import fitness
import scoring

FINAL_STATUSES = ("settled", "refunded")


def recompute(session: Session, challenge: db.Challenge, user_id: int) -> scoring.ScoreSheet:
    """Fetches the player's activities for the challenge and replaces their stored points."""
    provider = fitness.get_provider()
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    sheet = scoring.score_daily_mover(
        provider.fetch_activities(session, user_id, start, end),
        start,
        end,
        counts_manual=provider.counts_manual,
        requires_device=provider.requires_device,
    )
    if challenge.status in FINAL_STATUSES:
        return sheet  # the result is already onchain; stored points no longer change
    session.execute(
        delete(db.ScoreEntry).where(db.ScoreEntry.challenge_id == challenge.id, db.ScoreEntry.user_id == user_id)
    )
    for day in sheet.days.values():
        session.add(
            db.ScoreEntry(
                challenge_id=challenge.id, user_id=user_id, day=day.day, points=day.points, active=day.active,
                source=provider.name, source_activity_ids=json.dumps(day.activity_ids),
            )
        )
    session.commit()
    return sheet


def challenges_of(session: Session, user_id: int) -> list[db.Challenge]:
    return list(
        session.scalars(
            select(db.Challenge)
            .join(db.Participant, db.Participant.challenge_id == db.Challenge.id)
            .where(db.Participant.user_id == user_id)
            .order_by(db.Challenge.start_time)
        )
    )


def recompute_user(session: Session, user_id: int) -> dict[str, scoring.ScoreSheet]:
    """Recomputes every challenge the user is in. Returns {challenge address: score sheet}."""
    return {c.address: recompute(session, c, user_id) for c in challenges_of(session, user_id)}


def display_name(user: db.User) -> str:
    return user.display_name or (user.email or "").split("@")[0] or "Player"


def leaderboard(session: Session, challenge: db.Challenge, now: datetime | None = None) -> list[dict]:
    """Every player with their total points and daily ticks, best first. Tied players share a rank."""
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    now = min(now or datetime.now(timezone.utc), end)
    days_so_far = max(0, math.ceil((now - start) / scoring.DAY))
    entries: dict[int, dict[int, db.ScoreEntry]] = {}
    for entry in session.scalars(select(db.ScoreEntry).where(db.ScoreEntry.challenge_id == challenge.id)):
        entries.setdefault(entry.user_id, {})[entry.day] = entry
    rows = []
    players = session.execute(
        select(db.User, db.Participant)
        .join(db.Participant, db.Participant.user_id == db.User.id)
        .where(db.Participant.challenge_id == challenge.id)
    )
    for user, _participant in players:
        days = entries.get(user.id, {})
        rows.append(
            {
                "user_id": user.id,
                "name": display_name(user),
                "wallet": user.wallet_address,
                "points": sum(e.points for e in days.values()),
                "ticks": [bool(days[d].active) if d in days else False for d in range(days_so_far)],
            }
        )
    rows.sort(key=lambda r: (-r["points"], r["name"].lower()))
    for i, row in enumerate(rows):
        tied_with_previous = i > 0 and rows[i - 1]["points"] == row["points"]
        row["rank"] = rows[i - 1]["rank"] if tied_with_previous else i + 1
    return rows


def forget_user(session: Session, user_id: int) -> None:
    """Disconnect: deletes the user's fitness data, their link to the provider, and all their points."""
    try:
        fitness.get_provider().disconnect(session, user_id)
    except fitness.NotSupported:
        pass
    session.execute(delete(db.FitnessConnection).where(db.FitnessConnection.user_id == user_id))
    unsettled = select(db.Challenge.id).where(db.Challenge.status.not_in(FINAL_STATUSES))
    session.execute(
        delete(db.ScoreEntry).where(db.ScoreEntry.user_id == user_id, db.ScoreEntry.challenge_id.in_(unsettled))
    )
    session.commit()
