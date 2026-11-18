"""The "Daily Mover" scoring rules. Pure functions: activities in, points out. No database, no network.

Per day of the challenge (day 0 is the first 24 hours after the start):
    1 point if the day has at least 20 active minutes (this is also the "daily tick")
  + 1 point for every full 5 km covered that day
  capped at 3 points per day.

Anti-cheat: an activity is ignored (with a reason) if it is a duplicate, typed in by hand when the
source does not allow that, missing a recording device when one is required, outside the challenge
window, impossibly fast or long, or overlapping an activity that already counted.

Every activity ends in one state for a challenge (shown privately to its owner):
    verified  counted, and recorded by a device
    flagged   counted, but typed in by hand, so nobody can vouch for it
    rejected  not counted; `ScoreSheet.rejected` says why

The rules carry a version and a fingerprint (a SHA-256 of the numbers below). Both go into the
score sheet whose hash is stored onchain, so a result always names the exact rules it used.
Change any number below and bump RULES_VERSION.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from fitness.base import Activity

RULES_VERSION = "daily-mover-v1"
ACTIVE_MINUTES_FOR_TICK = 20
KM_PER_POINT = 5
MAX_POINTS_PER_DAY = 3
MAX_ACTIVITY_MINUTES = 24 * 60
MAX_SPEED_KMH = {"run": 25, "walk": 10, "hike": 10, "ride": 80, "swim": 8}  # faster than this is not believable
DEFAULT_MAX_SPEED_KMH = 25
DAY = timedelta(days=1)


def rules_fingerprint() -> str:
    """SHA-256 (hex) of the scoring numbers, written as compact JSON with sorted keys."""
    rules = {
        "version": RULES_VERSION,
        "active_minutes_for_tick": ACTIVE_MINUTES_FOR_TICK,
        "km_per_point": KM_PER_POINT,
        "max_points_per_day": MAX_POINTS_PER_DAY,
        "max_activity_minutes": MAX_ACTIVITY_MINUTES,
        "max_speed_kmh": MAX_SPEED_KMH,
        "default_max_speed_kmh": DEFAULT_MAX_SPEED_KMH,
        "day_seconds": int(DAY.total_seconds()),
    }
    return hashlib.sha256(json.dumps(rules, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


@dataclass
class DayScore:
    day: int
    minutes: float = 0
    km: float = 0
    activity_ids: list[str] = field(default_factory=list)

    @property
    def active(self) -> bool:
        return self.minutes >= ACTIVE_MINUTES_FOR_TICK

    @property
    def points(self) -> int:
        return min(MAX_POINTS_PER_DAY, int(self.active) + int(self.km // KM_PER_POINT))


@dataclass
class ScoreSheet:
    days: dict[int, DayScore] = field(default_factory=dict)
    rejected: dict[str, str] = field(default_factory=dict)  # activity ID -> why it did not count
    flagged: set[str] = field(default_factory=set)  # counted, but typed in by hand

    @property
    def total(self) -> int:
        return sum(day.points for day in self.days.values())

    def verdict(self, activity_id: str) -> tuple[str, str | None]:
        """(state, reason) for one activity. Activities this sheet never saw were outside its dates."""
        if activity_id in self.rejected:
            return "rejected", self.rejected[activity_id]
        if activity_id in self.flagged:
            return "flagged", "typed in by hand, so it counts but is not device-recorded"
        if any(activity_id in day.activity_ids for day in self.days.values()):
            return "verified", None
        return "rejected", "outside the challenge dates"


def _problem(activity: Activity, start: datetime, end: datetime, counts_manual: bool, requires_device: bool) -> str | None:
    if activity.is_manual and not counts_manual:
        return "typed in by hand"
    if requires_device and not activity.device:
        return "no recording device"
    if not (start <= activity.start < end):
        return "outside the challenge dates"
    if not (0 < activity.minutes <= MAX_ACTIVITY_MINUTES) or activity.distance_km < 0:
        return "not a valid activity"
    speed = activity.distance_km / (activity.minutes / 60)
    if speed > MAX_SPEED_KMH.get(activity.type, DEFAULT_MAX_SPEED_KMH):
        return "impossibly fast"
    return None


def score_daily_mover(
    activities: list[Activity],
    start: datetime,
    end: datetime,
    *,
    counts_manual: bool = True,
    requires_device: bool = False,
) -> ScoreSheet:
    sheet = ScoreSheet()
    seen: set[str] = set()
    busy_until: datetime | None = None  # when the latest counted activity finishes
    for activity in sorted(activities, key=lambda a: (a.start, a.id)):
        if activity.id in seen:
            continue  # the very same activity delivered twice
        seen.add(activity.id)
        problem = _problem(activity, start, end, counts_manual, requires_device)
        if problem is None and busy_until is not None and activity.start < busy_until:
            # Also catches the same workout uploaded twice under different IDs.
            problem = "overlaps another activity"
        if problem:
            sheet.rejected[activity.id] = problem
            continue
        finish = activity.start + timedelta(minutes=activity.minutes)
        busy_until = finish if busy_until is None else max(busy_until, finish)
        day = sheet.days.setdefault((activity.start - start) // DAY, DayScore((activity.start - start) // DAY))
        day.minutes += activity.minutes
        day.km += activity.distance_km
        day.activity_ids.append(activity.id)
        if activity.is_manual:
            sheet.flagged.add(activity.id)
    return sheet
