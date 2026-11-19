"""Proof of Sweat v1: the rules that turn an imported workout into checked, scored exercise time.

Pure functions: workouts and heart-rate samples in, checks and points out. No database, no network,
no randomness, so the same inputs always give the same result and every rule is easy to test.

Two questions are kept apart on purpose:
  1. Is this workout eligible?   Mandatory checks. All must pass.
  2. How strong is the evidence? Heart-rate coverage. This never changes the points.

Points reflect exercise participation; evidence strength reflects confidence in the recording.

Scoring (per 24-hour block counted from the challenge start):
    points = min(6, floor(eligible minutes / 10))
Eligible minutes are the minutes of verified workouts that fall inside the challenge, with any minute
covered by two workouts counted once. Distance, calories, heart rate and Oura's intensity estimate
never add points.

What this is not: proof that a person exercised. It checks the record an authorized Oura account
returned against the published rules below. The numbers are engineering thresholds, not medical or
scientifically validated fraud cut-offs. Change any of them and bump RULES_VERSION.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

RULES_VERSION = "proof-of-sweat-v1"
TEMPLATE = "proof_of_sweat_v1"  # stored on challenges.template
LEGACY_TEMPLATE = "daily_mover"

MINUTES_PER_POINT = 10
MAX_POINTS_PER_DAY = 6
MIN_ACTIVITY_MINUTES = 10
MAX_ACTIVITY_MINUTES = 24 * 60
FUTURE_TOLERANCE_SECONDS = 300  # a workout may not end later than this after the moment we check it
DAY = timedelta(days=1)

# Where Oura says a workout record came from (its `source` field).
ELIGIBLE_SOURCES = ("confirmed", "autodetected", "workout_heart_rate", "live_oura_heart_rate")
# Accepted, but never rated above limited evidence until its provenance is better understood.
CONSERVATIVE_SOURCES = ("live_third_party_heart_rate",)
REJECTED_SOURCES = ("manual",)

# Faster than this is not believable for the category. None: no cap (mixed sports, gym work).
MAX_SPEED_KMH = {"run": 25, "walk": 10, "hike": 10, "ride": 80, "swim": 8, "workout": None}

# Heart-rate evidence. Samples are grouped into one-minute bins so that hundreds of closely spaced
# readings count as coverage of time, not as hundreds of independent proofs.
BIN_SECONDS = 60
STRONG_COVERAGE = 0.5  # share of the workout's bins that hold a usable sample
STRONG_MIN_BINS = 5  # and at least this many distinct covered minutes
BPM_RANGE = (25, 250)  # outside this a reading is treated as a sensor error, never as a verdict on effort
WORKOUT_HR_SOURCES = ("workout", "live")  # recorded during exercise, unlike background "awake" or "rest" readings

PASSED, LIMITED, FAILED, PENDING = "passed", "limited", "failed", "pending"
VERIFIED, REJECTED = "verified", "rejected"
STRONG = "strong"


def rules() -> dict:
    """Every number and list above, as one value. Its hash names the exact rules a result used."""
    return {
        "version": RULES_VERSION,
        "minutes_per_point": MINUTES_PER_POINT,
        "max_points_per_day": MAX_POINTS_PER_DAY,
        "min_activity_minutes": MIN_ACTIVITY_MINUTES,
        "max_activity_minutes": MAX_ACTIVITY_MINUTES,
        "day_seconds": int(DAY.total_seconds()),
        "eligible_sources": list(ELIGIBLE_SOURCES),
        "conservative_sources": list(CONSERVATIVE_SOURCES),
        "max_speed_kmh": MAX_SPEED_KMH,
        "overlap_policy": "union",
        "heart_rate": {
            "bin_seconds": BIN_SECONDS,
            "strong_coverage": STRONG_COVERAGE,
            "strong_min_bins": STRONG_MIN_BINS,
            "bpm_range": list(BPM_RANGE),
            "workout_sources": list(WORKOUT_HR_SOURCES),
            "affects_points": False,
        },
    }


def rules_fingerprint() -> str:
    """SHA-256 (hex) of the rules, written as compact JSON with sorted keys."""
    return hashlib.sha256(json.dumps(rules(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


SUMMARY = "1 point for every 10 minutes of Oura-verified exercise, up to 6 points a day."


# ---------- one workout, on its own ----------


@dataclass(frozen=True)
class Workout:
    ref: str  # our private, stable name for the record; never the provider's ID
    provider: str  # where we fetched it from, through the user's authorized connection
    type: str | None  # Rival category (run, walk, hike, ride, swim, workout); None if we don't map it
    provider_source: str | None  # Oura's `source`
    start: datetime | None  # UTC
    end: datetime | None  # UTC
    distance_km: float | None = None


@dataclass(frozen=True)
class Check:
    code: str
    result: str  # passed, limited, failed or pending
    reason: str | None = None  # a short code; the app turns it into a sentence


def minutes_of(workout: Workout) -> float:
    if not (workout.start and workout.end):
        return 0.0
    return (workout.end - workout.start).total_seconds() / 60


def assess(workout: Workout, now: datetime, authorized_providers: tuple[str, ...] = ("oura",)) -> list[Check]:
    """The mandatory checks that depend only on the workout itself. Any `failed` means not eligible."""
    checks = [Check("provider", PASSED if workout.provider in authorized_providers else FAILED,
                    None if workout.provider in authorized_providers else "unauthorized_provider")]

    source = workout.provider_source
    if source in ELIGIBLE_SOURCES or source in CONSERVATIVE_SOURCES:
        checks.append(Check("provenance", PASSED))
    else:
        checks.append(Check("provenance", FAILED, "manual_entry" if source in REJECTED_SOURCES else "unknown_source"))

    checks.append(Check("activity", PASSED) if workout.type in MAX_SPEED_KMH
                  else Check("activity", FAILED, "unsupported_activity"))

    start, end = workout.start, workout.end
    if not (start and end) or start.tzinfo is None or end.tzinfo is None:
        return checks + [Check("timestamps", FAILED, "missing_time"), Check("duration", FAILED, "missing_time"),
                         Check("plausibility", FAILED, "missing_time")]
    minutes = (end - start).total_seconds() / 60
    if end <= start:
        timing = Check("timestamps", FAILED, "ends_before_start")
    elif minutes > MAX_ACTIVITY_MINUTES:
        timing = Check("timestamps", FAILED, "too_long")
    elif end > now + timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
        timing = Check("timestamps", FAILED, "in_the_future")
    else:
        timing = Check("timestamps", PASSED)
    checks.append(timing)
    checks.append(Check("duration", PASSED) if minutes >= MIN_ACTIVITY_MINUTES
                  else Check("duration", FAILED, "under_minimum"))

    distance = workout.distance_km
    cap = MAX_SPEED_KMH.get(workout.type or "")
    if distance is None:
        checks.append(Check("plausibility", PASSED, "no_distance"))  # absent distance is never a reason to reject
    elif not math.isfinite(distance) or distance < 0:
        checks.append(Check("plausibility", FAILED, "invalid_distance"))
    elif cap is not None and minutes > 0 and distance / (minutes / 60) > cap:
        checks.append(Check("plausibility", FAILED, "too_fast"))
    else:
        checks.append(Check("plausibility", PASSED))
    return checks


def first_failure(checks: list[Check]) -> str | None:
    return next((c.reason or c.code for c in checks if c.result == FAILED), None)


# ---------- heart-rate evidence ----------


@dataclass(frozen=True)
class Evidence:
    """What we keep about a workout's heart-rate samples. Never the readings themselves."""

    bins_total: int  # one-minute bins in the workout (a short last minute counts as a bin)
    bins_covered: int  # bins holding at least one usable sample
    workout_tagged: bool  # at least one usable sample was recorded as exercise, not background
    warning: bool  # some samples were malformed or outside the sensor range

    @property
    def coverage(self) -> float:
        return self.bins_covered / self.bins_total if self.bins_total else 0.0


def _time(value) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def heart_evidence(samples: list, start: datetime, end: datetime) -> Evidence:
    """Bins the samples that fall inside [start, end) by minute. Readings are read once and dropped."""
    seconds = max(0.0, (end - start).total_seconds())
    total = math.ceil(seconds / BIN_SECONDS)
    covered: set[int] = set()
    tagged = warning = False
    for sample in samples if isinstance(samples, list) else []:
        if not isinstance(sample, dict):
            warning = True
            continue
        at = _time(sample.get("timestamp"))
        if at is None:
            warning = True
            continue
        if not (start <= at < end):
            continue  # outside the workout: not evidence for it, and not an error either
        bpm = sample.get("bpm")
        if isinstance(bpm, bool) or not isinstance(bpm, (int, float)) or not (BPM_RANGE[0] <= bpm <= BPM_RANGE[1]):
            warning = True
            continue
        covered.add(int((at - start).total_seconds() // BIN_SECONDS))
        tagged = tagged or sample.get("source") in WORKOUT_HR_SOURCES
    return Evidence(total, len(covered), tagged, warning)


def evidence_check(evidence: Evidence | None, provider_source: str | None, unavailable: bool = False) -> Check:
    """Strong or limited. Limited is not a failure: the workout still earns its normal points."""
    if evidence is None:
        return Check("evidence", LIMITED, "heart_rate_unavailable") if unavailable else Check("evidence", PENDING)
    if evidence.bins_covered == 0:
        return Check("evidence", LIMITED, "no_heart_rate")
    if not evidence.workout_tagged:
        return Check("evidence", LIMITED, "background_only")
    if evidence.coverage < STRONG_COVERAGE or evidence.bins_covered < STRONG_MIN_BINS:
        return Check("evidence", LIMITED, "low_coverage")
    if provider_source in CONSERVATIVE_SOURCES:
        return Check("evidence", LIMITED, "third_party_source")
    return Check("evidence", PASSED, "quality_warning" if evidence.warning else None)


# ---------- a participant's workouts inside one challenge ----------


@dataclass(frozen=True)
class Item:
    """A workout with the outcome of its own checks: verified, rejected or pending."""

    workout: Workout
    status: str
    reason: str | None = None


@dataclass
class Line:
    """One workout's result in one challenge."""

    ref: str
    status: str  # verified, rejected or pending
    reason: str | None = None
    window: str = PASSED
    overlap: str = PASSED  # passed; limited when part of it was already covered by another workout
    eligible_seconds: int = 0
    points: int = 0
    days: dict[int, int] = field(default_factory=dict)  # challenge day -> credited seconds

    @property
    def eligible_minutes(self) -> int:
        return self.eligible_seconds // 60


@dataclass
class DaySweat:
    day: int
    seconds: int = 0
    activity_ids: list[str] = field(default_factory=list)

    @property
    def minutes(self) -> int:
        return self.seconds // 60

    @property
    def points(self) -> int:
        return min(MAX_POINTS_PER_DAY, self.seconds // (MINUTES_PER_POINT * 60))

    @property
    def active(self) -> bool:
        return self.points >= 1


@dataclass
class SweatSheet:
    days: dict[int, DaySweat] = field(default_factory=dict)
    lines: dict[str, Line] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return sum(day.points for day in self.days.values())

    @property
    def eligible_minutes(self) -> int:
        return sum(day.minutes for day in self.days.values())

    @property
    def rejected(self) -> dict[str, str]:
        return {ref: line.reason or "rejected" for ref, line in self.lines.items() if line.status == REJECTED}


def _subtract(segment: tuple[datetime, datetime], taken: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    """The parts of `segment` not already inside any interval of `taken` (sorted, non-overlapping)."""
    free, cursor = [], segment[0]
    for a, b in taken:
        if b <= cursor:
            continue
        if a >= segment[1]:
            break
        if a > cursor:
            free.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < segment[1]:
        free.append((cursor, segment[1]))
    return free


def _merge(taken: list[tuple[datetime, datetime]], extra: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for a, b in sorted(taken + extra):
        if merged and a <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], b))
        else:
            merged.append((a, b))
    return merged


def score(items: list[Item], start: datetime, end: datetime) -> SweatSheet:
    """Scores one participant's workouts for a challenge running over [start, end).

    Order is fixed (start time, then ref), so the result never depends on import order. Each workout
    is cut to the challenge window, then credited only for time no earlier workout already covered:
    overlapping records count as the union of their time, never twice. Credited time is split at the
    24-hour day boundaries, so a workout across a boundary feeds both days.
    """
    sheet = SweatSheet()
    taken: list[tuple[datetime, datetime]] = []
    seen: set[str] = set()
    ordered = sorted(items, key=lambda i: (i.workout.start or datetime.max.replace(tzinfo=timezone.utc), i.workout.ref))
    for item in ordered:
        workout = item.workout
        if workout.ref in seen:
            continue  # the same record delivered twice
        seen.add(workout.ref)
        if not (workout.start and workout.end) or workout.end <= start or workout.start >= end:
            continue  # no usable time, or outside this challenge altogether: not this challenge's business
        if item.status != VERIFIED:
            sheet.lines[workout.ref] = Line(workout.ref, item.status, item.reason,
                                            window=PASSED, overlap=PENDING if item.status == PENDING else PASSED)
            continue
        inside = (max(workout.start, start), min(workout.end, end))
        if (inside[1] - inside[0]).total_seconds() < MIN_ACTIVITY_MINUTES * 60:
            sheet.lines[workout.ref] = Line(workout.ref, REJECTED, "under_minimum_in_window", window=FAILED)
            continue
        fresh = _subtract(inside, taken)
        credited = sum(int((b - a).total_seconds()) for a, b in fresh)
        if credited == 0:
            sheet.lines[workout.ref] = Line(workout.ref, REJECTED, "duplicate_time", overlap=FAILED)
            continue
        whole = int((inside[1] - inside[0]).total_seconds())
        line = Line(workout.ref, VERIFIED, overlap=PASSED if credited == whole else LIMITED,
                    reason=None if credited == whole else "partly_overlapping")
        for a, b in fresh:
            cursor = a
            while cursor < b:
                index = (cursor - start) // DAY
                stop = min(b, start + (index + 1) * DAY)
                seconds = int((stop - cursor).total_seconds())
                day = sheet.days.setdefault(index, DaySweat(index))
                before = day.points
                day.seconds += seconds
                if workout.ref not in day.activity_ids:
                    day.activity_ids.append(workout.ref)
                line.points += day.points - before
                line.days[index] = line.days.get(index, 0) + seconds
                line.eligible_seconds += seconds
                cursor = stop
        taken = _merge(taken, fresh)
        sheet.lines[workout.ref] = line
    return sheet
