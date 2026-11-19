"""Turns a player's activities into stored points, and builds the leaderboard.

`score_entries` holds points and activity IDs only. Activity details stay with the fitness provider
and are only ever shown to their owner.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import db
import fitness
import formats
import leaguestats
import pickrounds
import scoring
import sweat
from fitness import oura, oura_sync

FINAL_STATUSES = ("settled", "refunded")


def is_sweat(challenge: db.Challenge) -> bool:
    """Proof of Sweat challenges score only workouts imported from each player's own Oura connection."""
    return challenge.template == sweat.TEMPLATE and not uses_league_stats(challenge)


def rules_of(challenge: db.Challenge) -> dict:
    """Which fitness rules a challenge uses. Fixed when it is created; never changed afterwards."""
    if uses_league_stats(challenge):
        return {"name": "league_stats", "version": leaguestats.RULES_VERSION, "sha256": None,
                "proof_of_sweat": False, "summary": "Points come from the league's stat sheet."}
    if is_sweat(challenge):
        return {"name": sweat.TEMPLATE, "version": sweat.RULES_VERSION, "sha256": sweat.rules_fingerprint(),
                "proof_of_sweat": True, "summary": sweat.SUMMARY}
    return {"name": challenge.template, "version": scoring.RULES_VERSION, "sha256": scoring.rules_fingerprint(),
            "proof_of_sweat": False,
            "summary": "Earlier rules: workouts logged in the app, not device-verified. Up to 3 points a day."}


def imported_rows(session: Session, challenge: db.Challenge, user_id: int) -> list[db.ImportedActivity]:
    """The player's imported workouts that touch the challenge's dates."""
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    return list(session.scalars(
        select(db.ImportedActivity)
        .where(db.ImportedActivity.user_id == user_id, db.ImportedActivity.end_time > start,
               db.ImportedActivity.start_time < end)
        .order_by(db.ImportedActivity.start_time, db.ImportedActivity.id)
    ))


def sweat_sheet(session: Session, challenge: db.Challenge, user_id: int) -> sweat.SweatSheet:
    """Proof of Sweat score for one player, from stored imported workouts only. Never calls Oura."""
    items = [sweat.Item(oura_sync.as_workout(row), row.status, row.reason)
             for row in imported_rows(session, challenge, user_id)]
    return sweat.score(items, db.utc(challenge.start_time), db.utc(challenge.end_time))


def sheet_for(session: Session, challenge: db.Challenge, user_id: int):
    """The player's score for the challenge, worked out from their activities. Stores nothing."""
    if uses_league_stats(challenge):
        return scoring.ScoreSheet()  # points come from the uploaded stat sheet, not workouts
    if is_sweat(challenge):
        return sweat_sheet(session, challenge, user_id)
    provider = fitness.get_provider()
    start, end = db.utc(challenge.start_time), db.utc(challenge.end_time)
    return scoring.score_daily_mover(
        provider.fetch_activities(session, user_id, start, end),
        start,
        end,
        counts_manual=provider.counts_manual,
        requires_device=provider.requires_device,
    )


def recompute(session: Session, challenge: db.Challenge, user_id: int, commit: bool = True):
    """Works out the player's score for the challenge and replaces their stored points.

    The player's row in the challenge is locked first (Postgres), so two recomputes for the same
    player run one after the other instead of both deleting and inserting at once.
    """
    if uses_league_stats(challenge):
        return scoring.ScoreSheet()
    source = oura_sync.PROVIDER if is_sweat(challenge) else fitness.get_provider().name
    sheet = sheet_for(session, challenge, user_id)
    if challenge.status in FINAL_STATUSES:
        return sheet  # the result is already onchain; stored points no longer change
    session.execute(
        select(db.Participant.id)
        .where(db.Participant.challenge_id == challenge.id, db.Participant.user_id == user_id)
        .with_for_update()
    )
    if session.scalar(select(db.Challenge.status).where(db.Challenge.id == challenge.id)) in FINAL_STATUSES:
        return sheet  # settled while we waited for the lock
    session.execute(
        delete(db.ScoreEntry).where(db.ScoreEntry.challenge_id == challenge.id, db.ScoreEntry.user_id == user_id)
    )
    for day in sheet.days.values():
        session.add(
            db.ScoreEntry(
                challenge_id=challenge.id, user_id=user_id, day=day.day, points=day.points, active=day.active,
                source=source, source_activity_ids=json.dumps(day.activity_ids),
            )
        )
    if commit:
        try:
            session.commit()
        except IntegrityError:  # a simultaneous recompute stored the same days (databases without row locks)
            session.rollback()
    else:
        session.flush()
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


def forget_user(session: Session, user_id: int) -> bool:
    """Deletes the user's fitness data: workouts logged in the app, the Oura link (revoked at Oura where
    possible), imported workouts, saved receipts, and their points in challenges that have not finished.
    Finished results, and anything onchain, stay. Returns whether Oura confirmed the revocation."""
    try:
        fitness.get_provider().disconnect(session, user_id)
    except fitness.NotSupported:
        pass
    revoked = oura.disconnect(session, user_id)  # revokes, then deletes tokens and imported workouts
    oura_sync.forget(session, user_id, receipts=True)
    session.execute(delete(db.FitnessConnection).where(db.FitnessConnection.user_id == user_id))
    unsettled = select(db.Challenge.id).where(db.Challenge.status.not_in(FINAL_STATUSES))
    session.execute(
        delete(db.ScoreEntry).where(db.ScoreEntry.user_id == user_id, db.ScoreEntry.challenge_id.in_(unsettled))
    )
    session.commit()
    return revoked
