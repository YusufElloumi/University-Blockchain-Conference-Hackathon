"""Imports a connected user's Oura workouts, checks them (api/sweat.py), and keeps the import tidy.

    sync_user          fetch the needed date range, add or update one row per workout, check what is new
    reconcile_challenge  before settlement: make sure every player's workouts are as current as we can get
    cleanup            delete imported workouts no recent challenge needs
    forget             delete everything imported for one user (disconnect)

Idempotent: syncing again updates or confirms rows and never adds a second row for the same workout
(a database unique constraint enforces it). Leaderboards and settlement read only the stored rows,
so they never wait on Oura.

Kept per workout: category, Oura's activity and provenance labels, UTC start and end, distance, the
check results, and heart-rate coverage as minute-bin counts. Not kept: Oura's workout ID (only a
one-way reference), calories, intensity, labels, the raw reply, or any heart-rate reading.
Nothing from Oura is written to the logs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import threading
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
import db
import sweat
import sweat2
import sweat3
from fitness import oura, oura_data

PROVIDER = oura.PROVIDER
FIRST_SYNC_DAYS = 30
OVERLAP_DAYS = 3  # each later sync looks this far back again, to catch edits and late arrivals
MIN_SYNC_INTERVAL = timedelta(seconds=30)  # per user; also stops two syncs running at once
MAX_WORKOUT_PAGES = 10
MAX_HR_FETCHES = 25  # heart-rate windows read per sync; the rest stay pending until the next one
MAX_HR_ATTEMPTS = 3  # then the workout is rated limited evidence instead of waiting forever
MAX_FINAL_SYNC_ATTEMPTS = 3  # per player, before settlement stops waiting for them
SWEAT_TEMPLATES = (sweat.TEMPLATE, sweat2.TEMPLATE, sweat3.TEMPLATE)
EFFORT_ENGINES = {sweat2.TEMPLATE: sweat2, sweat3.TEMPLATE: sweat3}  # rule sets that use a personal heart-rate reference
MISSING_SYNCS_BEFORE_REMOVAL = 2  # complete syncs in a row that must miss a workout before we drop it

# Oura activity names -> Rival categories. Names are compared in lower case with punctuation removed.
# Anything not listed is "unsupported" and earns nothing, rather than being guessed at.
ACTIVITY_MAP = {
    "run": ("running", "run", "treadmill", "trailrunning", "jogging", "indoorrunning", "outdoorrunning"),
    "walk": ("walking", "walk", "indoorwalking", "outdoorwalking", "nordicwalking", "powerwalking"),
    "hike": ("hiking", "hike", "trekking", "mountaineering", "backpacking"),
    "ride": ("cycling", "indoorcycling", "outdoorcycling", "biking", "mountainbiking", "roadcycling", "spinning",
             "ebiking", "bicycling"),
    "swim": ("swimming", "swim", "openwaterswimming", "poolswimming", "lapswimming"),
    "workout": (
        "strengthtraining", "weighttraining", "weightlifting", "functionaltraining", "functionalstrengthtraining",
        "corestrength", "coretraining", "crosstraining", "crossfit", "hiit", "highintensityintervaltraining",
        "circuittraining", "cardiotraining", "cardio", "bootcamp", "calisthenics", "elliptical", "ellipticaltrainer",
        "rowing", "indoorrowing", "rowingmachine", "stairexercise", "stairclimbing", "stairs", "stepper", "aerobics",
        "pilates", "yoga", "barre", "dance", "dancing", "zumba", "boxing", "kickboxing", "martialarts", "wrestling",
        "climbing", "rockclimbing", "bouldering", "jumprope", "gymnastics", "trx",
        "tennis", "tabletennis", "badminton", "squash", "padel", "pickleball", "racquetball",
        "soccer", "football", "americanfootball", "basketball", "volleyball", "beachvolleyball", "handball", "rugby",
        "hockey", "icehockey", "fieldhockey", "floorball", "lacrosse", "baseball", "softball", "cricket", "netball",
        "ultimatefrisbee", "waterpolo", "golf",
        "skiing", "downhillskiing", "crosscountryskiing", "snowboarding", "snowshoeing", "iceskating", "skating",
        "rollerskating", "inlineskating", "skateboarding",
        "kayaking", "canoeing", "paddling", "paddleboarding", "standuppaddleboarding", "surfing", "sailing",
        "horsebackriding", "workout", "exercise", "training",
    ),
}
_CATEGORY = {name: category for category, names in ACTIVITY_MAP.items() for name in names}

log = logging.getLogger("loser_buys")
_local = threading.Lock()
_running: set[int] = set()  # users syncing in this process right now


def category_of(provider_activity) -> str | None:
    """The Rival category for an Oura activity name, or None when we do not support it."""
    if not isinstance(provider_activity, str):
        return None
    return _CATEGORY.get(re.sub(r"[^a-z0-9]", "", provider_activity.lower()))


def reference(provider_workout_id: str) -> str:
    """Our private name for a provider workout. One-way, so the provider's ID is not stored."""
    return hashlib.sha256(f"rival.proof-of-sweat.activity|{PROVIDER}|{provider_workout_id}".encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize(raw: dict) -> dict | None:
    """One Oura workout cut down to the fields we keep. None if it has no usable ID."""
    workout_id = raw.get("id") if isinstance(raw, dict) else None
    if not isinstance(workout_id, str) or not workout_id:
        return None
    start, end = oura_data._when(raw.get("start_datetime")), oura_data._when(raw.get("end_datetime"))
    metres = raw.get("distance")
    distance = None
    if isinstance(metres, (int, float)) and not isinstance(metres, bool) and math.isfinite(metres):
        distance = round(metres / 1000, 3)
    activity = raw.get("activity") if isinstance(raw.get("activity"), str) else None
    source = raw.get("source") if isinstance(raw.get("source"), str) else None
    intensity = raw.get("intensity") if raw.get("intensity") in sweat2.PROVIDER_FACTOR else None
    fields = {
        "provider_ref": reference(workout_id),
        "activity_type": category_of(activity),
        "provider_activity": activity[:60] if activity else None,
        "provider_source": source[:60] if source else None,
        "intensity": intensity,
        "start_time": start,
        "end_time": end,
        "minutes": round((end - start).total_seconds() / 60, 2) if start and end else 0.0,
        "distance_km": distance,
    }
    shape = [activity, source, start.isoformat() if start else None, end.isoformat() if end else None, distance,
             intensity]
    fields["content_hash"] = hashlib.sha256(json.dumps(shape).encode()).hexdigest()
    return fields


def as_workout(row: db.ImportedActivity) -> sweat.Workout:
    return sweat.Workout(
        ref=f"{row.provider}:{row.id}", provider=row.provider, type=row.activity_type,
        provider_source=row.provider_source,
        start=db.utc(row.start_time) if row.start_time else None,
        end=db.utc(row.end_time) if row.end_time else None,
        distance_km=row.distance_km,
    )


def checks_of(row: db.ImportedActivity) -> list[sweat.Check]:
    return [sweat.Check(c["code"], c["result"], c.get("reason")) for c in json.loads(row.checks or "[]")]


def _save_checks(row: db.ImportedActivity, checks: list[sweat.Check]) -> None:
    row.checks = json.dumps([{"code": c.code, "result": c.result, "reason": c.reason} for c in checks])


def _reset(row: db.ImportedActivity) -> None:
    row.status, row.assurance, row.reason, row.checks = "pending", None, None, None
    row.hr_bins_total = row.hr_bins_covered = row.verified_at = None
    row.hr_usable = row.hr_quarters = row.hr_tagged_bins = row.hr_warning = row.hr_median = None
    row.hr_attempts = 0


def _open_sweat_challenges(session: Session, user_id: int) -> list[db.Challenge]:
    return list(session.scalars(
        select(db.Challenge)
        .join(db.Participant, db.Participant.challenge_id == db.Challenge.id)
        .where(db.Participant.user_id == user_id, db.Challenge.status == "open",
               db.Challenge.template.in_(SWEAT_TEMPLATES))
    ))


def _claim(session: Session, connection_id: int, now: datetime, interval: timedelta) -> bool:
    """Takes this user's sync slot in the database. False if a sync started less than `interval` ago."""
    claimed = session.execute(
        update(db.FitnessConnection)
        .where(db.FitnessConnection.id == connection_id,
               or_(db.FitnessConnection.last_sync_attempt_at.is_(None),
                   db.FitnessConnection.last_sync_attempt_at <= now - interval))
        .values(last_sync_attempt_at=now)
        .execution_options(synchronize_session=False)
    )
    session.commit()
    return claimed.rowcount == 1


def _fail(session: Session, user_id: int, code: str) -> None:
    session.rollback()
    session.execute(
        update(db.FitnessConnection)
        .where(db.FitnessConnection.user_id == user_id, db.FitnessConnection.provider == PROVIDER)
        .values(last_sync_error=code)
        .execution_options(synchronize_session=False)
    )
    session.commit()


def sync_user(session: Session, user_id: int, now: datetime | None = None,
              interval: timedelta | None = None) -> dict:
    """Brings one user's imported workouts up to date and checks the new ones. Returns a short summary."""
    now = now or _now()
    interval = MIN_SYNC_INTERVAL if interval is None else interval
    connection = oura._connection(session, user_id)
    if connection is None:
        raise oura.OuraError("Connect Oura first.", 404)
    with _local:
        if user_id in _running:
            raise oura.OuraError("A sync is already running. Give it a moment.", 409)
        _running.add(user_id)
    try:
        if not _claim(session, connection.id, now, interval):
            raise oura.OuraError("Your workouts were synced a moment ago. Try again shortly.", 429)
        try:
            summary = _sync(session, user_id, now)
        except oura.OuraError as e:
            _fail(session, user_id, {401: "reconnect", 403: "permission", 429: "rate_limited"}.get(e.status, "unreachable"))
            raise
        except Exception:
            _fail(session, user_id, "error")
            raise
    finally:
        with _local:
            _running.discard(user_id)
    import scores  # here, not at the top: scores imports this module

    for challenge in _open_sweat_challenges(session, user_id):
        scores.recompute(session, challenge, user_id)
    return summary


def _sync(session: Session, user_id: int, now: datetime) -> dict:
    token = oura.access_token(session, user_id)  # refreshes if needed; raises 401 when the link is dead
    connection = oura._connection(session, user_id)
    floor = now - timedelta(days=FIRST_SYNC_DAYS)
    if connection.last_sync_at is None:
        since = floor
    else:
        since = db.utc(connection.last_sync_at) - timedelta(days=OVERLAP_DAYS)
        for challenge in _open_sweat_challenges(session, user_id):
            since = min(since, db.utc(challenge.start_time) - timedelta(days=1))
            if challenge.template in EFFORT_ENGINES and not _reference_frozen(session, challenge, user_id):
                # v2 compares effort with the player's earlier workouts: look back far enough to build that reference.
                since = min(since, db.utc(challenge.start_time) - timedelta(days=sweat2.REFERENCE_WINDOW_DAYS))
        since = max(since, floor)
    raws, complete = oura_data.pages(
        oura_data.WORKOUT_URL, token,
        {"start_date": since.date().isoformat(), "end_date": (now.date() + timedelta(days=1)).isoformat()},
        max_pages=MAX_WORKOUT_PAGES,
    )

    counts = {"found": 0, "new": 0, "updated": 0, "skipped": 0}
    seen: set[str] = set()
    for raw in raws:
        fields = normalize(raw)
        if fields is None or fields["provider_ref"] in seen:
            counts["skipped"] += fields is None
            continue
        seen.add(fields["provider_ref"])
        counts["found"] += 1
        row = session.scalar(select(db.ImportedActivity).where(
            db.ImportedActivity.provider == PROVIDER, db.ImportedActivity.provider_ref == fields["provider_ref"]))
        if row is None:
            try:
                with session.begin_nested():
                    session.add(db.ImportedActivity(user_id=user_id, provider=PROVIDER, first_seen_at=now,
                                                    synced_at=now, rules_version=sweat2.RULES_VERSION, **fields))
                counts["new"] += 1
            except IntegrityError:  # another request imported it a moment ago
                counts["skipped"] += 1
            continue
        if row.user_id != user_id:
            counts["skipped"] += 1  # already imported by another Rival account: never credited twice
            continue
        if row.content_hash != fields["content_hash"]:
            for name, value in fields.items():
                setattr(row, name, value)
            _reset(row)  # edited at the provider: check it again from scratch
            counts["updated"] += 1
        elif row.reason == "removed_at_provider":
            _reset(row)
        row.synced_at, row.missing_syncs = now, 0

    session.flush()
    mine = select(db.ImportedActivity).where(db.ImportedActivity.user_id == user_id,
                                             db.ImportedActivity.provider == PROVIDER)
    if complete:
        # Only a full listing says anything about absence, and only repeated absence is believed.
        checked_from = since + timedelta(days=1)
        for row in session.scalars(mine.where(db.ImportedActivity.start_time >= checked_from)):
            if row.provider_ref in seen or row.reason == "removed_at_provider":
                continue
            row.missing_syncs = (row.missing_syncs or 0) + 1
            if row.missing_syncs >= MISSING_SYNCS_BEFORE_REMOVAL:
                row.status, row.assurance, row.reason = "rejected", None, "removed_at_provider"

    _verify_pending(session, user_id, token, now)
    connection.last_sync_at, connection.last_sync_error = now, None
    session.commit()

    rows = list(session.scalars(mine))
    return {
        "synced_at": now.isoformat(),
        "complete": complete,
        **counts,
        "verified": sum(1 for r in rows if r.status == "verified"),
        "pending": sum(1 for r in rows if r.status == "pending"),
        "rejected": sum(1 for r in rows if r.status == "rejected"),
    }


def _verify_pending(session: Session, user_id: int, token: str, now: datetime) -> None:
    """Runs the checks on every pending workout, newest first. Heart rate is read once and not kept."""
    pending = list(session.scalars(
        select(db.ImportedActivity)
        .where(db.ImportedActivity.user_id == user_id, db.ImportedActivity.provider == PROVIDER,
               db.ImportedActivity.status == "pending")
        .order_by(db.ImportedActivity.start_time.desc(), db.ImportedActivity.id)
    ))
    fetches = 0
    heart_rate_refused = False
    for row in pending:
        workout = as_workout(row)
        checks = sweat.assess(workout, now)
        row.rules_version = sweat2.RULES_VERSION
        failure = sweat.first_failure(checks)
        if failure:
            row.status, row.assurance, row.reason, row.verified_at = "rejected", None, failure, now
            _save_checks(row, checks)
            continue
        evidence, unavailable = None, heart_rate_refused
        if not heart_rate_refused:
            if fetches >= MAX_HR_FETCHES:
                _save_checks(row, checks + [sweat.Check("evidence", sweat.PENDING)])
                continue
            fetches += 1
            try:
                samples, _ = oura_data.pages(oura_data.HEARTRATE_URL, token, {
                    "start_datetime": workout.start.isoformat(), "end_datetime": workout.end.isoformat()})
                heart = sweat2.heart_summary(samples, workout.start, workout.end)
                evidence = sweat.Evidence(heart.bins_total, heart.bins_covered, heart.tagged, heart.warning)
                del samples  # reduced to counts and one median; the readings are never stored
            except oura.OuraError as e:
                if e.status == 401:
                    raise
                if e.status == 403:
                    heart_rate_refused = unavailable = True  # permission missing: don't ask again this sync
                else:
                    row.hr_attempts = (row.hr_attempts or 0) + 1
                    unavailable = row.hr_attempts >= MAX_HR_ATTEMPTS
                    if not unavailable:
                        _save_checks(row, checks + [sweat.Check("evidence", sweat.PENDING)])
                        continue
        check = sweat.evidence_check(evidence, workout.provider_source, unavailable=unavailable)
        row.status, row.verified_at = "verified", now
        row.assurance = sweat.STRONG if check.result == sweat.PASSED else sweat.LIMITED
        row.reason = check.reason
        row.hr_bins_total = evidence.bins_total if evidence else None
        row.hr_bins_covered = evidence.bins_covered if evidence else None
        if evidence:
            row.hr_usable, row.hr_quarters, row.hr_tagged_bins = heart.usable, heart.quarters, heart.tagged_bins
            row.hr_warning, row.hr_median = heart.warning, heart.median
        _save_checks(row, checks + [check])


# ---------- Proof of Sweat v2: stored heart summary and the frozen personal reference ----------


def heart_of(row: db.ImportedActivity) -> sweat2.HeartSummary | None:
    """The heart-rate summary kept for a workout, or None when none was read (or it predates v2)."""
    if row.hr_bins_total is None or row.hr_usable is None:
        return None
    return sweat2.HeartSummary(
        bins_total=row.hr_bins_total, bins_covered=row.hr_bins_covered or 0, usable=row.hr_usable,
        quarters=row.hr_quarters or 0, tagged=bool(row.hr_tagged_bins), warning=bool(row.hr_warning),
        tagged_bins=row.hr_tagged_bins or 0, median=row.hr_median,
    )


def _reference_frozen(session: Session, challenge: db.Challenge, user_id: int) -> bool:
    return session.scalar(select(db.Participant.hr_reference_at).where(
        db.Participant.challenge_id == challenge.id, db.Participant.user_id == user_id)) is not None


def freeze_reference(session: Session, challenge: db.Challenge, user_id: int, now: datetime | None = None) -> None:
    """Fixes a player's personal reference for a v2 challenge, once. Does not commit.

    Built only from workouts that ended before the challenge started (so effort inside the challenge
    cannot move it) and inside the reference window, each with enough exercise-tagged heart rate.
    Frozen from the challenge start onwards: with a reference as soon as there is one; without one
    only after the player has synced at least once, so a late first sync still gets its chance.
    """
    now = now or _now()
    start = db.utc(challenge.start_time)
    participant = session.scalar(select(db.Participant).where(
        db.Participant.challenge_id == challenge.id, db.Participant.user_id == user_id))
    if participant is None or participant.hr_reference_at is not None or now < start:
        return
    rows = session.scalars(
        select(db.ImportedActivity)
        .where(db.ImportedActivity.user_id == user_id, db.ImportedActivity.status == "verified",
               db.ImportedActivity.hr_median.is_not(None), db.ImportedActivity.end_time <= start,
               db.ImportedActivity.start_time >= start - timedelta(days=sweat2.REFERENCE_WINDOW_DAYS))
        .order_by(db.ImportedActivity.start_time.desc(), db.ImportedActivity.id)
    )
    engine = EFFORT_ENGINES.get(challenge.template, sweat2)
    reference = engine.personal_reference([r.hr_median for r in rows if sweat2.qualifies_for_heart(heart_of(r))])
    if reference is None:
        connection = oura._connection(session, user_id)
        if connection is None or connection.last_sync_at is None:
            return  # nothing has been synced yet: decide once it has
    participant.hr_reference = json.dumps(reference) if reference else None
    participant.hr_reference_at = now


# ---------- before settlement ----------


def reconcile_challenge(session: Session, challenge: db.Challenge, end: datetime, force: bool = False,
                        now: datetime | None = None) -> tuple[bool, dict[int, str]]:
    """Makes each player's imported workouts as current as we can get before the final scores are fixed.

    Returns (ready, {user_id: state}). A player is `complete` once a sync has finished after the
    challenge ended with nothing left pending in its window; `not_connected` if they have no Oura
    link; `unavailable` after MAX_FINAL_SYNC_ATTEMPTS failed tries, or when `force` ends the wait.
    The same rule applies to every player. A failed sync never adds or removes points by itself.
    """
    now = now or _now()
    states: dict[int, str] = {}
    participants = list(session.scalars(select(db.Participant).where(db.Participant.challenge_id == challenge.id)))
    for participant in participants:
        user_id = participant.user_id
        connection = oura._connection(session, user_id)
        if connection is None:
            states[user_id] = "not_connected"
            continue
        if _settled_for(session, connection, user_id, challenge, end):
            states[user_id] = "complete"
            continue
        if (participant.final_sync_attempts or 0) >= MAX_FINAL_SYNC_ATTEMPTS:
            states[user_id] = "unavailable"
            continue
        participant.final_sync_attempts = (participant.final_sync_attempts or 0) + 1
        session.commit()
        try:
            sync_user(session, user_id, now=now, interval=min(MIN_SYNC_INTERVAL, timedelta(seconds=5)))
        except oura.OuraError as e:
            log.warning("Final Oura sync for a player failed (HTTP %s)", e.status)
        except Exception:
            session.rollback()
            log.exception("Final Oura sync for a player failed")
        connection = oura._connection(session, user_id)
        if connection is None:
            states[user_id] = "not_connected"  # the link was dead and has been removed
        elif _settled_for(session, connection, user_id, challenge, end):
            states[user_id] = "complete"
        else:
            states[user_id] = "unavailable" if force else "pending"
    ready = force or "pending" not in states.values()
    return ready, {u: ("unavailable" if s == "pending" else s) for u, s in states.items()}


def _settled_for(session: Session, connection: db.FitnessConnection, user_id: int, challenge: db.Challenge,
                 end: datetime) -> bool:
    if connection.last_sync_at is None or db.utc(connection.last_sync_at) < end:
        return False
    return session.scalar(
        select(db.ImportedActivity.id).where(
            db.ImportedActivity.user_id == user_id, db.ImportedActivity.status == "pending",
            db.ImportedActivity.end_time > db.utc(challenge.start_time), db.ImportedActivity.start_time < end)
    ) is None


# ---------- retention ----------


def cleanup(session: Session, now: datetime | None = None) -> int:
    """Deletes imported workouts that no open or recently ended challenge of their owner needs.

    A workout is kept while it falls inside a challenge its owner plays that is still open or ended
    less than EVIDENCE_RETENTION_DAYS ago; otherwise it goes once it is that many days old.
    Final receipts (sweat_receipts) and points are separate, minimal records and are not touched.
    """
    now = now or _now()
    cutoff = now - timedelta(days=config.EVIDENCE_RETENTION_DAYS)
    removed = 0
    old = session.scalars(select(db.ImportedActivity).where(
        or_(db.ImportedActivity.end_time < cutoff,
            (db.ImportedActivity.end_time.is_(None)) & (db.ImportedActivity.first_seen_at < cutoff))))
    for row in list(old):
        needed = row.start_time is not None and row.end_time is not None and session.scalar(
            select(db.Challenge.id)
            .join(db.Participant, db.Participant.challenge_id == db.Challenge.id)
            .where(db.Participant.user_id == row.user_id, db.Challenge.template.in_(SWEAT_TEMPLATES),
                   db.Challenge.start_time < row.end_time, db.Challenge.end_time > row.start_time,
                   or_(db.Challenge.status == "open", db.Challenge.end_time > cutoff))
        ) is not None
        if not needed and row.end_time is not None:
            # Also kept: workouts a v2 challenge still needs to build a player's reference (not frozen yet).
            needed = any(
                db.utc(row.end_time) <= db.utc(c.start_time)
                and db.utc(row.end_time) >= db.utc(c.start_time) - timedelta(days=sweat2.REFERENCE_WINDOW_DAYS)
                and not _reference_frozen(session, c, row.user_id)
                for c in _open_sweat_challenges(session, row.user_id) if c.template in EFFORT_ENGINES
            )
        if not needed:
            session.delete(row)
            removed += 1
    session.commit()
    return removed


def forget(session: Session, user_id: int, receipts: bool = False) -> None:
    """Deletes a user's imported workouts (and, on a full data deletion, their saved receipts). Does not commit."""
    session.execute(delete(db.ImportedActivity).where(db.ImportedActivity.user_id == user_id))
    if receipts:
        # A full deletion also drops the heart-rate reference kept for unfinished challenges.
        open_ids = select(db.Challenge.id).where(db.Challenge.status == "open")
        session.execute(update(db.Participant).where(db.Participant.user_id == user_id,
                                                     db.Participant.challenge_id.in_(open_ids))
                        .values(hr_reference=None).execution_options(synchronize_session=False))
        session.execute(delete(db.SweatReceipt).where(db.SweatReceipt.user_id == user_id))
