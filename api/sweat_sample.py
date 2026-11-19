"""Made-up workouts scored by the real Proof of Sweat code, for the website's sample receipt.

The public "How it works" calculator runs in the browser (web/src/sweatMath.ts). To keep it the same
arithmetic as the server and not an approximation, two files are generated from here and committed:

    web/src/sweatRules.json        every scoring number, straight from sweat3.rules(); the browser
                                   code reads its constants from this file and holds none of its own
    web/scripts/sweat-vectors.json several hundred made-up workouts with the server's answers

`pytest` fails if either file is out of date (tests/test_sweat3.py); `npm run check:sweat` in web/
fails if the browser code gives a different answer for any of them. After changing a rule:

    python sweat_sample.py write        (in api/, venv)

Nothing here is real data. A sample is one workout on its own challenge day, recorded by Oura, with
every mandatory check passed. It goes through scores.score_rows and scores.sweat2_detail, the same
functions that score and describe a real imported workout.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from itertools import product
from pathlib import Path

import db
import scores
import sweat
import sweat3
from fitness import oura_sync

WEB = Path(__file__).resolve().parent.parent / "web"
RULES_FILE = WEB / "src" / "sweatRules.json"
VECTORS_FILE = WEB / "scripts" / "sweat-vectors.json"

START = datetime(2026, 1, 5, tzinfo=timezone.utc)  # an arbitrary challenge start; nothing depends on it
REFERENCE = {"median": 100, "workouts": 6}  # so "N% above usual" is a session median of 100 + N


def sample(activity: str, minutes: int, intensity: str | None, heart_pct: int | None, distance_km: float | None,
           hr_minutes: int, quarters: int, engine=sweat3) -> dict:
    """The receipt breakdown for one made-up workout.

    heart_pct    the session's heart rate against the player's own usual level, in percent; None = no reference
    hr_minutes   minutes of the workout that hold a heart-rate sample recorded as exercise (0 = none at all)
    quarters     how many quarters of the workout those samples fall in
    """
    begins = START + timedelta(hours=1)
    row = db.ImportedActivity(
        id=1, user_id=0, provider=oura_sync.PROVIDER, provider_ref="sample", activity_type=activity,
        provider_source="confirmed", start_time=begins, end_time=begins + timedelta(minutes=minutes),
        minutes=minutes, distance_km=distance_km, content_hash="sample", status=sweat.VERIFIED, intensity=intensity,
    )
    if hr_minutes > 0:
        row.hr_bins_total, row.hr_bins_covered, row.hr_usable = minutes, hr_minutes, hr_minutes
        row.hr_tagged_bins, row.hr_quarters, row.hr_warning = hr_minutes, quarters, False
        row.hr_median = 100 + (heart_pct or 0)
    reference = REFERENCE if heart_pct is not None else None
    sheet = scores.score_rows([row], reference, START, START + timedelta(days=7), engine)
    line = sheet.lines[oura_sync.as_workout(row).ref]
    return scores.sweat2_detail(row, line, reference, engine)


def digest(detail: dict) -> list:
    """The numbers of a breakdown, compactly, for comparing thousands of cases."""
    score, evidence = detail["score"], detail["evidence"]
    factors = [[f["value"], f["state"], f["reason"], f["bonus"]] for f in
               (score["factors"][k] for k in ("provider", "heart", "movement"))]
    return [evidence["index"], evidence["label"], [p["points"] for p in evidence["parts"]], score["band_minutes"],
            score["base_points"], factors, score["multiplier"], score["potential_bonus"], score["reliability"],
            score["adjusted_bonus"], score["contribution"]]


# Speeds (km/h) on both sides of every pace band, never exactly on an edge.
SPEEDS = {"run": [7, 9, 11, 13], "walk": [3.5, 4.8, 6, 7], "hike": [2.5, 4, 5], "ride": [13, 18, 25, 30],
          "swim": [1.2, 2, 2.8, 3.5], "workout": []}


def cases() -> list[list]:
    """A fixed spread of inputs: every 61st of the full grid, plus the grid's corners."""
    grid = []
    for activity, minutes, intensity, heart_pct, share in product(
            SPEEDS, (10, 20, 40, 60, 90, 150, 200), (None, "easy", "moderate", "hard"),
            (None, -12, -8, -3, 0, 5, 10, 15, 25), (0, 0.33, 0.5, 0.7, 1)):
        hr_minutes = round(minutes * share)
        quarters = 0 if hr_minutes == 0 else 2 if share < 0.5 else 3 if share < 1 else 4
        for speed in [None, *SPEEDS[activity]]:
            distance = None if speed is None else round(speed * minutes / 60, 2)
            grid.append([activity, minutes, intensity, heart_pct, distance, hr_minutes, quarters])
    return grid[::61] + [grid[0], grid[-1]]


def vectors() -> dict:
    listed = cases()
    return {
        "rules_version": sweat3.RULES_VERSION,
        "rules_sha256": sweat3.rules_fingerprint(),
        "note": "Made-up workouts scored by api/sweat_sample.py. Generated; do not edit by hand.",
        "full": [{"in": c, "out": sample(*c)} for c in listed[:: max(1, len(listed) // 6)]],
        "cases": [[c, digest(sample(*c))] for c in listed],
    }


def rules_text() -> str:
    return json.dumps({"sha256": sweat3.rules_fingerprint(), "rules": sweat3.rules()}, indent=2, sort_keys=True) + "\n"


def vectors_text() -> str:
    return json.dumps(vectors(), sort_keys=True, separators=(",", ":")) + "\n"


if __name__ == "__main__":
    if sys.argv[1:] != ["write"]:
        sys.exit("usage: python sweat_sample.py write")
    RULES_FILE.write_text(rules_text())
    VECTORS_FILE.parent.mkdir(exist_ok=True)
    VECTORS_FILE.write_text(vectors_text())
    print(f"wrote {RULES_FILE.name} and {VECTORS_FILE.name} ({len(cases())} cases), rules {sweat3.rules_fingerprint()[:12]}...")
