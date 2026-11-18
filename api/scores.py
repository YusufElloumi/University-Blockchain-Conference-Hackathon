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
import formats
import leaguestats
import pickrounds
import scoring

FINAL_STATUSES = ("settled", "refunded")


def sheet_for(session: Session, challenge: db.Challenge, user_id: int) -> scoring.ScoreSheet:
    """The player's score for the challenge, worked out from their activities. Stores nothing."""
    if uses_league_stats(challenge):
        return scoring.ScoreSheet()  # points come from the uploaded stat sheet, not workouts
    provider = fitness.get_provider()
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    return scoring.score_daily_mover(
        provider.fetch_activities(session, user_id, start, end),
        start,
        end,
        counts_manual=provider.counts_manual,
        requires_device=provider.requires_device,
    )


def recompute(session: Session, challenge: db.Challenge, user_id: int) -> scoring.ScoreSheet:
    """Fetches the player's activities for the challenge and replaces their stored points."""
    if uses_league_stats(challenge):
        return scoring.ScoreSheet()
    provider = fitness.get_provider()
    sheet = sheet_for(session, challenge, user_id)
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


def uses_league_stats(challenge: db.Challenge) -> bool:
    return challenge.scoring_source == "league_stats"


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
    """Every player with their total points and daily ticks, best first. Tied players share a rank.

    Total = main points (fitness, or league stats) + prediction pick points, to one decimal place.
    """
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    now = min(now or datetime.now(timezone.utc), end)
    days_so_far = max(0, math.ceil((now - start) / scoring.DAY))
    entries: dict[int, dict[int, db.ScoreEntry]] = {}
    for entry in session.scalars(select(db.ScoreEntry).where(db.ScoreEntry.challenge_id == challenge.id)):
        entries.setdefault(entry.user_id, {})[entry.day] = entry
    stats = leaguestats.points_by_user(session, challenge) if uses_league_stats(challenge) else None
    picks = pickrounds.points_by_user(session, challenge)
    rows = []
    players = session.execute(
        select(db.User, db.Participant)
        .join(db.Participant, db.Participant.user_id == db.User.id)
        .where(db.Participant.challenge_id == challenge.id)
    )
    for user, participant in players:
        days = entries.get(user.id, {})
        base = stats.get(user.id, 0) if stats is not None else sum(e.points for e in days.values())
        pick_points = picks.get(user.id, 0.0)
        rows.append(
            {
                "user_id": user.id,
                "name": display_name(user),
                "wallet": user.wallet_address,
                "points": _tidy(base + pick_points),
                "base_points": _tidy(base),
                "pick_points": _tidy(pick_points),
                "active_days": sum(1 for e in days.values() if e.active),
                "team": participant.team,
                # League stats have no daily ticks.
                "ticks": [] if stats is not None else
                [bool(days[d].active) if d in days else False for d in range(days_so_far)],
            }
        )
    rows.sort(key=lambda r: (-r["points"], r["name"].lower()))
    for i, row in enumerate(rows):
        tied_with_previous = i > 0 and rows[i - 1]["points"] == row["points"]
        row["rank"] = rows[i - 1]["rank"] if tied_with_previous else i + 1
    return rows


def entries(board: list[dict]) -> list[formats.Entry]:
    """Leaderboard rows in the shape the payout rules take."""
    return [formats.Entry(r["wallet"], r["points"], r["active_days"], r["team"]) for r in board if r["wallet"]]


def format_view(challenge: db.Challenge, board: list[dict]) -> dict:
    """The format, its settings, and what each player would win if the event ended right now.

    `projected` maps user_id -> share of the pool in percent. Teams also get a team table; goal
    events get each player's progress towards the goal.
    """
    fmt, config = formats.of(challenge)
    view: dict = {"format": fmt, "config": config, "summary": formats.describe(fmt, config), "projected": {}}
    found = entries(board)
    if found:
        by_wallet = {r["wallet"]: r["user_id"] for r in board}
        result = formats.payout(fmt, config, found)
        view["projected"] = {by_wallet[w]: bps / 100 for w, bps in result.shares}
        view["goal_missed"] = result.goal_missed
    if fmt == "teams":
        view["teams"] = formats.team_scores(found, config["teams"])
        # Teams nobody has joined yet still show, with no score.
        listed = {t["team"] for t in view["teams"]}
        view["teams"] += [{"team": i, "name": n, "average": None, "members": 0, "rank": None}
                          for i, n in enumerate(config["teams"]) if i not in listed]
    if fmt == "goal":
        view["progress"] = {r["user_id"]: formats.goal_progress(formats.Entry(r["wallet"], r["points"], r["active_days"]), config)
                            for r in board}
    return view


def _tidy(points: float) -> float | int:
    """One decimal place; whole numbers stay whole (3, not 3.0)."""
    points = round(points, 1)
    return int(points) if points == int(points) else points


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
