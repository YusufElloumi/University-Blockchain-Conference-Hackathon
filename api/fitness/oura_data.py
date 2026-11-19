"""Read-only look at a connected user's Oura workouts, to learn what Oura really returns.

A test step before Proof of Sweat, not part of scoring. It:
  - reads recent workouts from Oura's API v2 with the user's own token (refreshed by oura.access_token);
  - reports each workout's fields, and which documented fields are missing or empty;
  - for each workout, counts heart-rate samples inside its time window and how much of it they cover.
    Heart-rate values (bpm) are never returned, stored or logged: only counts, coverage and sources.

Nothing is written to the database. Nothing from Oura is logged (errors log the HTTP status only).
Oura API reference: https://cloud.ouraring.com/v2/docs (OpenAPI 1.43, checked Nov 2026).
"""

from __future__ import annotations

import logging
import math
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from fitness import oura

API = "https://api.ouraring.com/v2/usercollection"
WORKOUT_URL = f"{API}/workout"
HEARTRATE_URL = f"{API}/heartrate"
MAX_PAGES = 5  # per request; plenty for a test window, and bounds the calls we make

# From Oura's OpenAPI schema `PublicWorkout`.
WORKOUT_REQUIRED = ("id", "activity", "day", "start_datetime", "end_datetime", "intensity", "source")
WORKOUT_OPTIONAL = ("calories", "distance", "label")
WORKOUT_FIELDS = WORKOUT_REQUIRED + WORKOUT_OPTIONAL

log = logging.getLogger("loser_buys")


RETRIES = 3  # tries per request for timeouts, 5xx and 429, with a short doubling wait between them
_sleep = time.sleep  # replaced in tests


def _request(url: str, token: str, params: dict) -> dict:
    """One Oura API request with bounded retries. Errors never include Oura's reply."""
    failure: oura.OuraError | None = None
    for attempt in range(RETRIES):
        if attempt:
            _sleep(0.5 * 2 ** (attempt - 1))
        try:
            response = httpx.get(url, params=params, headers={**oura.HEADERS, "Authorization": f"Bearer {token}"},
                                 timeout=20)
        except httpx.HTTPError as e:
            log.warning("Oura data request failed: %s", type(e).__name__)
            failure = oura.OuraError("Couldn't reach Oura. Try again in a moment.", 502)
            continue
        if response.status_code == 200:
            try:
                body = response.json()
            except ValueError:
                body = None
            if not isinstance(body, dict) or not isinstance(body.get("data", []), list):
                log.warning("Oura data request returned an unreadable reply")
                raise oura.OuraError("Oura sent an unexpected reply. Try again in a moment.", 502)
            return body
        log.warning("Oura data request answered HTTP %s", response.status_code)
        failure = _error_for(response.status_code)
        if response.status_code not in (429, 500, 502, 503, 504):
            break  # 401, 403 and the like will not change on a retry
    raise failure or oura.OuraError("Couldn't reach Oura. Try again in a moment.", 502)


def pages(url: str, token: str, params: dict, max_pages: int = MAX_PAGES) -> tuple[list, bool]:
    """Rows from up to `max_pages` pages, and whether that was everything Oura had for the request."""
    rows: list = []
    params = dict(params)
    for _ in range(max_pages):
        body = _request(url, token, params)
        rows.extend(body.get("data") or [])
        if not body.get("next_token"):
            return rows, True
        params["next_token"] = body["next_token"]
    return rows, False


def _get(url: str, token: str, params: dict) -> list[dict]:
    """All pages of one Oura collection request (up to MAX_PAGES)."""
    return [row for row in pages(url, token, params)[0] if isinstance(row, dict)]


def _error_for(status: int) -> oura.OuraError:
    if status == 401:
        return oura.OuraError("Oura didn't accept Rival's access. Disconnect and connect Oura again.", 401)
    if status == 403:
        return oura.OuraError("Oura refused this data. The permission may not be granted, or the Oura "
                              "account may need an active membership.", 403)
    if status == 429:
        return oura.OuraError("Oura is rate limiting requests. Try again in a few minutes.", 429)
    return oura.OuraError(f"Oura answered with an error (HTTP {status}).", 502)


def _when(value) -> datetime | None:
    """Oura's timestamps carry a UTC offset (e.g. 2026-11-18T07:00:00-06:00). Returns UTC, or None."""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else None


def _present(value) -> bool:
    return value is not None and value != ""


def heart_rate_coverage(samples: list[dict], start: datetime, end: datetime) -> dict:
    """How well heart-rate samples cover a workout window. Counts only; bpm values are ignored."""
    duration_s = max(0.0, (end - start).total_seconds())
    times = sorted(t for t in (_when(s.get("timestamp")) for s in samples) if t is not None and start <= t <= end)
    sources: dict[str, int] = {}
    for sample in samples:
        t = _when(sample.get("timestamp"))
        if t is not None and start <= t <= end:
            name = str(sample.get("source") or "unknown")
            sources[name] = sources.get(name, 0) + 1
    minutes = math.ceil(duration_s / 60) if duration_s else 0
    covered = len({int((t - start).total_seconds() // 60) for t in times})
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return {
        "status": "ok",
        "sample_count": len(times),
        "workout_minutes": minutes,
        "minutes_with_samples": covered,
        "coverage_pct": round(100 * min(covered, minutes) / minutes, 1) if minutes else 0.0,
        "sources": sources,
        "median_gap_seconds": sorted(gaps)[len(gaps) // 2] if gaps else None,
        "first_sample_after_start_seconds": round((times[0] - start).total_seconds()) if times else None,
        "last_sample_before_end_seconds": round((end - times[-1]).total_seconds()) if times else None,
    }


def _summary(workout: dict) -> dict:
    start, end = _when(workout.get("start_datetime")), _when(workout.get("end_datetime"))
    distance = workout.get("distance")
    return {
        "id": workout.get("id"),
        "activity": workout.get("activity"),
        "label": workout.get("label"),
        "source": workout.get("source"),
        "intensity": workout.get("intensity"),
        "day": workout.get("day"),
        "start_datetime": workout.get("start_datetime"),  # as Oura sent it, with its UTC offset
        "end_datetime": workout.get("end_datetime"),
        "duration_minutes": round((end - start).total_seconds() / 60, 1) if start and end else None,
        "distance_m": distance,
        "distance_km": round(distance / 1000, 3) if isinstance(distance, (int, float)) else None,
        "calories": workout.get("calories"),
        "missing_fields": [f for f in WORKOUT_FIELDS if not _present(workout.get(f))],
        # Field names Oura sent that its documentation doesn't list (names only, never values).
        "undocumented_fields": sorted(k for k in workout if k not in WORKOUT_FIELDS),
    }


def recent_workouts(session: Session, user_id: int, days: int = 30, limit: int = 10, today: date | None = None) -> dict:
    """The caller's most recent Oura workouts with field and heart-rate coverage reports. Read-only."""
    token = oura.access_token(session, user_id)  # raises OuraError if not connected; refreshes if needed
    today = today or datetime.now(timezone.utc).date()
    start_date, end_date = today - timedelta(days=days), today + timedelta(days=1)
    workouts = _get(WORKOUT_URL, token, {"start_date": start_date.isoformat(), "end_date": end_date.isoformat()})
    workouts.sort(key=lambda w: str(w.get("start_datetime") or ""), reverse=True)
    chosen = workouts[:limit]

    summaries = [_summary(w) for w in chosen]
    heart_rate_error: str | None = None
    for workout, summary in zip(chosen, summaries):
        start, end = _when(workout.get("start_datetime")), _when(workout.get("end_datetime"))
        if not (start and end and end > start):
            summary["heart_rate"] = {"status": "skipped", "reason": "workout has no usable start and end time"}
            continue
        if heart_rate_error:
            summary["heart_rate"] = {"status": "unavailable", "reason": heart_rate_error}
            continue
        try:
            samples = _get(HEARTRATE_URL, token, {"start_datetime": start.isoformat(), "end_datetime": end.isoformat()})
        except oura.OuraError as e:
            if e.status in (401, 429, 502):
                raise
            heart_rate_error = str(e)  # e.g. 403: don't ask again for every workout
            summary["heart_rate"] = {"status": "unavailable", "reason": heart_rate_error}
            continue
        summary["heart_rate"] = heart_rate_coverage(samples, start, end)

    return {
        "window": {"start_date": start_date.isoformat(), "end_date": end_date.isoformat(), "days": days},
        "workouts_found": len(workouts),
        "workouts_shown": len(summaries),
        "documented_fields": {"required": list(WORKOUT_REQUIRED), "optional": list(WORKOUT_OPTIONAL)},
        "field_presence": {f: sum(1 for w in chosen if _present(w.get(f))) for f in WORKOUT_FIELDS},
        "workouts": summaries,
        "note": "Read-only check. Nothing was saved. Heart-rate values are not shown: only how many samples "
                "fall inside each workout and how much of it they cover.",
    }
