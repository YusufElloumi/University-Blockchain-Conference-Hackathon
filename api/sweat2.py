"""Proof of Sweat v2: multi-signal evidence and effort-weighted scoring. Pure functions, no database, no network.

v2 keeps v1's mandatory gates (api/sweat.py: provider, provenance, activity, timestamps, 10-minute
minimum, challenge window, overlap as union, speed ceilings) and adds two separate outputs:

  A. Evidence Index (0-100)   How complete and consistent the recorded evidence is. A rule-based
                              heuristic. NOT a probability that the workout happened, and never an
                              admission rule on its own: a failed gate rejects whatever the index says,
                              and a workout with no heart rate at all is still eligible.
  B. Sweat Score              Competition points: effective minutes x an effort multiplier.

The two do not feed each other. Confidence in a recording and effort in a session are different things.

Sweat Score, per 24-hour challenge day:
    effective minutes   the day's unique eligible minutes, in time order, weighted by band:
                        minutes 1-60 x 1.0, 61-120 x 0.60, 121-180 x 0.25, beyond 180 x 0
    effort multiplier   clamp(0.85, 1.25, 0.40*provider + 0.40*heart + 0.20*movement)
                        each factor is centred on 1.00; an unavailable signal IS 1.00 (no renormalizing,
                        so a sensor gap is never an advantage)
    contribution        a workout's effective minutes x its multiplier (kept as an exact decimal)
    day points          round half up (sum of the day's contributions)

Every constant below is a game-design or engineering heuristic, not exercise advice, a medical
threshold or a validated classifier. Change any of them and bump RULES_VERSION: a challenge locks
the fingerprint of these rules onchain (api/rules.py) and will not settle under different ones.
"""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

import sweat

RULES_VERSION = "proof-of-sweat-v2"
TEMPLATE = "proof_of_sweat_v2"  # stored on challenges.template
SUMMARY = ("About 1 Sweat Point per Oura-verified minute, weighted by effort (x0.85 to x1.25). "
           "Each day's first hour counts in full, then less.")

D = Decimal

# ---- B1. Effective minutes: diminishing returns per challenge day (anti-gaming, not exercise advice) ----
BANDS: tuple[tuple[int, Decimal], ...] = ((60, D("1.00")), (60, D("0.60")), (60, D("0.25")))  # (minutes, weight)

# ---- B2. Effort factors, each centred on 1.00 ----
PROVIDER_FACTOR = {"easy": D("0.90"), "moderate": D("1.00"), "hard": D("1.12")}  # Oura's own intensity label

# Heart rate, relative to the player's own earlier workouts ("personal observed workout reference").
# Never an absolute bpm threshold, an age formula, a resting or maximum heart rate, or a medical zone.
HR_MIN_COVERAGE = 0.5  # of the workout's one-minute bins must hold a usable exercise-tagged sample
HR_MIN_BINS = 10
HR_SLOPE = D("1.25")  # factor = 1 + slope * (session median / reference median - 1)
HR_RANGE = (D("0.90"), D("1.15"))
REFERENCE_MIN_WORKOUTS = 4  # fewer than this: no reference, factor neutral
REFERENCE_MAX_WORKOUTS = 10  # the most recent ones before the challenge start
REFERENCE_WINDOW_DAYS = 30

# Movement: average speed bands in km/h per category, (lower bound, factor), lowest first. Kept small
# because terrain, stops and conditions confound pace. Categories not listed have no movement signal.
MOVEMENT_BANDS: dict[str, tuple[tuple[float, Decimal], ...]] = {
    "run": ((0, D("0.95")), (8, D("1.00")), (10, D("1.05")), (12, D("1.10"))),
    "walk": ((0, D("0.95")), (4, D("1.00")), (5.5, D("1.05")), (6.5, D("1.10"))),
    "hike": ((0, D("0.97")), (3, D("1.00")), (4.5, D("1.05"))),
    "ride": ((0, D("0.95")), (15, D("1.00")), (22, D("1.05")), (28, D("1.10"))),
    "swim": ((0, D("0.95")), (1.5, D("1.00")), (2.5, D("1.05")), (3.2, D("1.10"))),
}

WEIGHTS = {"provider": D("0.40"), "heart": D("0.40"), "movement": D("0.20")}
MULTIPLIER_RANGE = (D("0.85"), D("1.25"))

# ---- A. Evidence Index weights (sum 100) ----
EVIDENCE = {
    "provenance": {"max": 35, "native": 35, "third_party": 20},
    "integrity": {"max": 25, "clean": 25, "overlap_resolved": 20},
    "movement": {"max": 15, "observed": 15, "unobserved": 7},
    "physiological": {"max": 25, "coverage": 15, "exercise_tagged": 5, "distribution": 3, "validity": 2},
}
STRONG_MIN_INDEX = 80
STRONG_MIN_SAMPLES = 10
STRONG_MIN_BINS = sweat.STRONG_MIN_BINS
STRONG_COVERAGE = sweat.STRONG_COVERAGE

MEASURED, ESTIMATED, UNAVAILABLE = "measured", "provider_estimated", "unavailable"


def rules() -> dict:
    """Every number above plus the v1 gates this version reuses. Its hash is what a challenge locks."""
    return {
        "version": RULES_VERSION,
        "gates": sweat.rules(),  # v2 keeps v1's mandatory checks exactly
        "bands": [[minutes, str(weight)] for minutes, weight in BANDS],
        "provider_factor": {k: str(v) for k, v in PROVIDER_FACTOR.items()},
        "heart": {
            "min_coverage": HR_MIN_COVERAGE, "min_bins": HR_MIN_BINS, "slope": str(HR_SLOPE),
            "range": [str(v) for v in HR_RANGE], "reference_min_workouts": REFERENCE_MIN_WORKOUTS,
            "reference_max_workouts": REFERENCE_MAX_WORKOUTS, "reference_window_days": REFERENCE_WINDOW_DAYS,
            "reference": "median of per-workout medians, workouts before the challenge start, frozen per player",
        },
        "movement_bands": {k: [[low, str(f)] for low, f in bands] for k, bands in MOVEMENT_BANDS.items()},
        "weights": {k: str(v) for k, v in WEIGHTS.items()},
        "multiplier_range": [str(v) for v in MULTIPLIER_RANGE],
        "unavailable_signal": "1.00, not renormalized",
        "rounding": "per-day total, round half up",
        "evidence_index": EVIDENCE,
        "strong_evidence": {"min_index": STRONG_MIN_INDEX, "min_samples": STRONG_MIN_SAMPLES,
                            "min_bins": STRONG_MIN_BINS, "min_coverage": STRONG_COVERAGE},
    }


def rules_fingerprint() -> str:
    """SHA-256 (hex) of the rules, written as compact JSON with sorted keys."""
    return hashlib.sha256(json.dumps(rules(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ---------- heart rate: one transient pass over the samples ----------


@dataclass(frozen=True)
class HeartSummary:
    """All that is kept of a workout's heart-rate samples. `median` is one number; no series is stored."""

    bins_total: int  # one-minute bins in the workout
    bins_covered: int  # bins with at least one usable sample
    usable: int  # usable samples (valid time inside the workout, bpm in the sensor range)
    quarters: int  # how many quarters of the workout hold a usable sample (0-4)
    tagged: bool  # at least one usable sample was recorded as exercise
    warning: bool  # some samples were malformed or out of range and were dropped
    tagged_bins: int = 0  # bins with an exercise-tagged usable sample
    median: int | None = None  # median of the per-minute medians of exercise-tagged samples

    @property
    def coverage(self) -> float:
        return self.bins_covered / self.bins_total if self.bins_total else 0.0

    @property
    def tagged_coverage(self) -> float:
        return self.tagged_bins / self.bins_total if self.bins_total else 0.0


def heart_summary(samples: list, start: datetime, end: datetime) -> HeartSummary:
    """Reduces heart-rate samples inside [start, end) to coverage counts and one median.

    Samples are grouped by minute first, so hundreds of readings in a minute weigh the same as one.
    """
    seconds = max(0.0, (end - start).total_seconds())
    total = math.ceil(seconds / sweat.BIN_SECONDS)
    covered: set[int] = set()
    quarters: set[int] = set()
    by_bin: dict[int, list[float]] = {}
    usable = 0
    warning = False
    for sample in samples if isinstance(samples, list) else []:
        if not isinstance(sample, dict):
            warning = True
            continue
        at = sweat._time(sample.get("timestamp"))
        if at is None:
            warning = True
            continue
        if not (start <= at < end):
            continue
        bpm = sample.get("bpm")
        if isinstance(bpm, bool) or not isinstance(bpm, (int, float)) or not (sweat.BPM_RANGE[0] <= bpm <= sweat.BPM_RANGE[1]):
            warning = True
            continue
        offset = (at - start).total_seconds()
        index = int(offset // sweat.BIN_SECONDS)
        usable += 1
        covered.add(index)
        quarters.add(min(3, int(4 * offset / seconds)) if seconds else 0)
        if sample.get("source") in sweat.WORKOUT_HR_SOURCES:
            by_bin.setdefault(index, []).append(float(bpm))
    median = round(statistics.median(statistics.median(v) for v in by_bin.values())) if by_bin else None
    return HeartSummary(total, len(covered), usable, len(quarters), bool(by_bin), warning, len(by_bin), median)


def personal_reference(medians: list[int]) -> dict | None:
    """The player's "personal observed workout reference": the median of their recent workouts' medians.

    `medians` are the stored per-workout medians of qualifying workouts that ended before the
    challenge started, most recent first. None when there are too few to be stable.
    """
    recent = [m for m in medians if isinstance(m, (int, float)) and m > 0][:REFERENCE_MAX_WORKOUTS]
    if len(recent) < REFERENCE_MIN_WORKOUTS:
        return None
    return {"median": round(statistics.median(recent)), "workouts": len(recent), "version": RULES_VERSION}


# ---------- the three effort factors ----------


@dataclass(frozen=True)
class Factor:
    value: Decimal
    state: str  # measured, provider_estimated or unavailable (unavailable is always exactly 1.00)
    reason: str | None = None  # short code
    detail: dict = field(default_factory=dict)  # owner-only numbers behind the value (never bpm)


def provider_factor(intensity: str | None) -> Factor:
    """Oura's own intensity label. It can be Oura's default when it had little to go on, so it is
    shown as provider-estimated, never as a physiological measurement."""
    if intensity in PROVIDER_FACTOR:
        return Factor(PROVIDER_FACTOR[intensity], ESTIMATED, intensity)
    return Factor(D("1.00"), UNAVAILABLE, "no_intensity")


def qualifies_for_heart(heart: HeartSummary | None) -> bool:
    """Enough exercise-tagged heart rate to say anything about the session."""
    return (heart is not None and heart.median is not None and heart.tagged_bins >= HR_MIN_BINS
            and heart.tagged_coverage >= HR_MIN_COVERAGE)


def heart_factor(heart: HeartSummary | None, reference: dict | None) -> Factor:
    """Effort relative to the player's own reference: 1 + 1.25 x (session / reference - 1), kept in [0.90, 1.15].

    Linear and monotonic: a session 8% above your usual level gives 1.10. Neutral whenever the
    session's heart rate or the reference is not good enough to trust, with the reason.
    """
    if heart is None or heart.bins_covered == 0:
        return Factor(D("1.00"), UNAVAILABLE, "no_heart_rate")
    if not qualifies_for_heart(heart):
        return Factor(D("1.00"), UNAVAILABLE, "not_enough_heart_rate")
    if not reference or not reference.get("median"):
        return Factor(D("1.00"), UNAVAILABLE, "no_personal_reference")
    ratio = D(heart.median) / D(reference["median"])
    value = min(HR_RANGE[1], max(HR_RANGE[0], D(1) + HR_SLOPE * (ratio - 1))).quantize(D("0.001"), ROUND_HALF_UP)
    percent = int(((ratio - 1) * 100).quantize(D("1"), ROUND_HALF_UP))
    return Factor(value, MEASURED, "relative_to_reference",
                  {"relative_percent": percent, "reference_workouts": reference.get("workouts")})


def speed_kmh(distance_km: float | None, minutes: float) -> float | None:
    if distance_km is None or not math.isfinite(distance_km) or distance_km <= 0 or minutes <= 0:
        return None
    return distance_km / (minutes / 60)


def movement_factor(category: str | None, distance_km: float | None, minutes: float) -> Factor:
    """A small pace adjustment for categories where distance means something. Otherwise neutral."""
    bands = MOVEMENT_BANDS.get(category or "")
    if bands is None:
        return Factor(D("1.00"), UNAVAILABLE, "no_pace_for_category")
    speed = speed_kmh(distance_km, minutes)
    if speed is None:
        return Factor(D("1.00"), UNAVAILABLE, "no_distance")
    value = bands[0][1]
    for low, factor in bands:
        if speed >= low:
            value = factor
    return Factor(value, MEASURED, "pace_band", {"speed_kmh": round(speed, 1)})


def effort_multiplier(provider: Factor, heart: Factor, movement: Factor) -> Decimal:
    raw = WEIGHTS["provider"] * provider.value + WEIGHTS["heart"] * heart.value + WEIGHTS["movement"] * movement.value
    return min(MULTIPLIER_RANGE[1], max(MULTIPLIER_RANGE[0], raw)).quantize(D("0.001"), ROUND_HALF_UP)


# ---------- A. Evidence Index ----------


def evidence_index(*, gates_passed: bool, provider_source: str | None, overlap_resolved: bool,
                   movement_observed: bool, heart: HeartSummary | None, heart_pending: bool = False) -> dict:
    """The four weighted parts, their sum, and a label. Explains itself; decides nothing by itself.

    Monotonic: more coverage, an exercise tag, better spread or cleaner samples never lower it.
    Missing signals score as "not observed" (0 of 25 for heart rate, 7 of 15 for movement), which is
    a statement about the evidence, never about the person.
    """
    native = provider_source in sweat.ELIGIBLE_SOURCES
    third = provider_source in sweat.CONSERVATIVE_SOURCES
    parts = []
    w = EVIDENCE["provenance"]
    parts.append({"key": "provenance", "max": w["max"],
                  "points": w["native"] if native else w["third_party"] if third else 0,
                  "state": "full" if native else "partial" if third else "failed",
                  "reason": None if native else "third_party_source" if third else "ineligible_source"})
    w = EVIDENCE["integrity"]
    parts.append({"key": "integrity", "max": w["max"],
                  "points": 0 if not gates_passed else w["overlap_resolved"] if overlap_resolved else w["clean"],
                  "state": "failed" if not gates_passed else "partial" if overlap_resolved else "full",
                  "reason": "gate_failed" if not gates_passed else "partly_overlapping" if overlap_resolved else None})
    w = EVIDENCE["movement"]
    parts.append({"key": "movement", "max": w["max"],
                  "points": w["observed"] if movement_observed else w["unobserved"],
                  "state": "full" if movement_observed else "unavailable",
                  "reason": None if movement_observed else "not_observed"})
    w = EVIDENCE["physiological"]
    if heart_pending:
        parts.append({"key": "physiological", "max": w["max"], "points": 0, "state": "pending", "reason": "pending"})
    elif heart is None or heart.bins_covered == 0:
        parts.append({"key": "physiological", "max": w["max"], "points": 0, "state": "unavailable",
                      "reason": "not_observed"})
    else:
        sub = {
            "coverage": math.floor(w["coverage"] * min(1.0, heart.coverage)),
            "exercise_tagged": w["exercise_tagged"] if heart.tagged else 0,
            "distribution": w["distribution"] if heart.quarters >= 3 else 0,
            "validity": 0 if heart.warning else w["validity"],
        }
        points = sum(sub.values())
        parts.append({"key": "physiological", "max": w["max"], "points": points,
                      "state": "full" if points == w["max"] else "partial", "sub": sub,
                      "reason": None if points == w["max"] else "background_only" if not heart.tagged
                      else "low_coverage" if heart.coverage < STRONG_COVERAGE else "partial_signal"})
    index = sum(p["points"] for p in parts)

    if not gates_passed:
        label, why = "rejected", []
    elif heart_pending:
        label, why = "pending", []
    else:
        why = []
        if heart is None or heart.bins_covered == 0:
            why.append("no_heart_rate")
        else:
            if not heart.tagged:
                why.append("background_only")
            if heart.coverage < STRONG_COVERAGE or heart.bins_covered < STRONG_MIN_BINS:
                why.append("low_coverage")
            if heart.usable < STRONG_MIN_SAMPLES:
                why.append("few_samples")
        if third:
            why.append("third_party_source")
        if not why and index < STRONG_MIN_INDEX:
            why.append("index_below_strong")
        label = "limited" if why else "strong"
    return {"index": index, "parts": parts, "label": label, "limits": why}


# ---------- B. Sweat Score for one participant in one challenge ----------


@dataclass(frozen=True)
class Item:
    """A workout with the outcome of its own gates and, when verified, its effort multiplier."""

    workout: sweat.Workout
    status: str  # verified, rejected or pending
    reason: str | None = None
    multiplier: Decimal = D("1.000")


@dataclass
class Line:
    """One workout's result in one challenge."""

    ref: str
    status: str
    reason: str | None = None
    window: str = sweat.PASSED
    overlap: str = sweat.PASSED
    eligible_seconds: int = 0
    multiplier: Decimal = D("1.000")
    effective_minutes: Decimal = D(0)
    contribution: Decimal = D(0)  # effective minutes x multiplier, exact
    bands: list[int] = field(default_factory=lambda: [0] * (len(BANDS) + 1))  # seconds per band; last = past the cap
    days: dict[int, int] = field(default_factory=dict)  # challenge day -> credited seconds

    @property
    def eligible_minutes(self) -> int:
        return self.eligible_seconds // 60

    @property
    def points(self) -> Decimal:
        """This workout's share of the score before the day is rounded, to two places for display."""
        return self.contribution.quantize(D("0.01"), ROUND_HALF_UP)


@dataclass
class DaySweat:
    day: int
    seconds: int = 0
    contribution: Decimal = D(0)
    activity_ids: list[str] = field(default_factory=list)

    @property
    def minutes(self) -> int:
        return self.seconds // 60

    @property
    def points(self) -> int:
        return int(self.contribution.quantize(D("1"), ROUND_HALF_UP))

    @property
    def active(self) -> bool:
        return self.seconds >= sweat.MIN_ACTIVITY_MINUTES * 60


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
        return {ref: line.reason or "rejected" for ref, line in self.lines.items() if line.status == sweat.REJECTED}


def effective_minutes(minutes: float) -> Decimal:
    """A day's effective minutes for `minutes` actual ones: 30 -> 30, 90 -> 78, 120 -> 96, 180 and up -> 111."""
    left, total = D(str(minutes)), D(0)
    for size, weight in BANDS:
        used = min(left, D(size))
        total += used * weight
        left -= used
    return total


def _allocate(used_seconds: int, seconds: int) -> list[int]:
    """Splits `seconds` of new time, starting after `used_seconds` already counted that day, across the bands."""
    out = [0] * (len(BANDS) + 1)
    position, left = used_seconds, seconds
    edge = 0
    for i, (size, _) in enumerate(BANDS):
        edge += size * 60
        if left <= 0:
            break
        if position < edge:
            take = min(left, edge - position)
            out[i] += take
            position += take
            left -= take
    out[-1] += max(0, left)
    return out


def score(items: list[Item], start: datetime, end: datetime) -> SweatSheet:
    """Scores one participant's workouts for a challenge running over [start, end).

    Same gates and overlap rule as v1 (fixed order by start time then ref; time already covered by an
    earlier workout is never credited again). New: each workout's credited time is laid, in that
    order, onto the day's diminishing bands, and multiplied by that workout's effort multiplier.
    Two 45-minute neutral workouts in a day therefore give 60 + 30 x 0.6 = 78, not 90.
    """
    sheet = SweatSheet()
    taken: list[tuple[datetime, datetime]] = []
    seen: set[str] = set()
    far = datetime.max.replace(tzinfo=timezone.utc)
    for item in sorted(items, key=lambda i: (i.workout.start or far, i.workout.ref)):
        workout = item.workout
        if workout.ref in seen:
            continue
        seen.add(workout.ref)
        if not (workout.start and workout.end) or workout.end <= start or workout.start >= end:
            continue  # no usable time, or wholly outside this challenge
        if item.status != sweat.VERIFIED:
            sheet.lines[workout.ref] = Line(workout.ref, item.status, item.reason, window=sweat.PASSED,
                                            overlap=sweat.PENDING if item.status == sweat.PENDING else sweat.PASSED)
            continue
        inside = (max(workout.start, start), min(workout.end, end))
        if (inside[1] - inside[0]).total_seconds() < sweat.MIN_ACTIVITY_MINUTES * 60:
            sheet.lines[workout.ref] = Line(workout.ref, sweat.REJECTED, "under_minimum_in_window", window=sweat.FAILED)
            continue
        fresh = sweat._subtract(inside, taken)
        credited = sum(int((b - a).total_seconds()) for a, b in fresh)
        if credited == 0:
            sheet.lines[workout.ref] = Line(workout.ref, sweat.REJECTED, "duplicate_time", overlap=sweat.FAILED)
            continue
        whole = int((inside[1] - inside[0]).total_seconds())
        line = Line(workout.ref, sweat.VERIFIED, multiplier=item.multiplier,
                    overlap=sweat.PASSED if credited == whole else sweat.LIMITED,
                    reason=None if credited == whole else "partly_overlapping")
        for a, b in fresh:
            cursor = a
            while cursor < b:
                index = (cursor - start) // sweat.DAY
                stop = min(b, start + (index + 1) * sweat.DAY)
                seconds = int((stop - cursor).total_seconds())
                day = sheet.days.setdefault(index, DaySweat(index))
                split = _allocate(day.seconds, seconds)
                effective = sum((D(s) * weight for s, (_, weight) in zip(split, BANDS)), D(0)) / D(60)
                contribution = effective * item.multiplier
                day.seconds += seconds
                day.contribution += contribution
                if workout.ref not in day.activity_ids:
                    day.activity_ids.append(workout.ref)
                line.bands = [x + y for x, y in zip(line.bands, split)]
                line.effective_minutes += effective
                line.contribution += contribution
                line.days[index] = line.days.get(index, 0) + seconds
                line.eligible_seconds += seconds
                cursor = stop
        taken = sweat._merge(taken, fresh)
        sheet.lines[workout.ref] = line
    return sheet
