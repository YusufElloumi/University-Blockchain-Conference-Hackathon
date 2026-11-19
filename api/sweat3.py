"""Proof of Sweat v3: v2 with effort made consequential. Pure functions, no database, no network.

Everything about verification is v2's, unchanged and imported from api/sweat2.py: the mandatory gates
(v1's), the Evidence Index, the daily bands, the reliability steps, the two-pass scoring and

    final = base + base x (effort multiplier - 1) x reliability

What v3 changes is how far the three effort signals can move a score, and their weights:

                      v2                         v3
    weights           40% Oura / 40% heart /     45% heart / 30% movement / 25% Oura intensity
                      20% movement
    multiplier        0.85 to 1.25               0.85 to 1.50
                      (signals could reach 1.13) (signals can reach the cap)
    Oura intensity    0.90 / 1.00 / 1.12         0.85 / 1.00 / 1.30
    heart rate        slope 1.25, 0.90-1.15      slope 3, 0.80-1.65
    movement bands    0.95 to 1.10               0.90 to 1.45

Why these weights: heart rate measured against the player's own reference is the hardest signal to
fake and the most personal, so it leads. Movement is measured but confounded by terrain. Oura's
intensity label is an estimate (and can be Oura's default), so it weighs least.

Safeguards kept from v2: an unavailable signal is exactly 1.00 and is never renormalized, so missing
data is neither a bonus nor a penalty and a sensor gap is never an advantage; the bonus counts only
in proportion to the Evidence Index; base points never depend on effort evidence; the day's
diminishing bands still apply; a failed gate is always zero. With no heart rate at all the
multiplier cannot pass 1.21.

A separate rule set from v2 on purpose: challenges that locked v2's fingerprint onchain keep
settling under api/sweat2.py, which must not change. Change any number here and bump RULES_VERSION.
Every constant is a game-design heuristic, not exercise advice or a medical threshold.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal

import sweat
import sweat2
from sweat2 import (  # noqa: F401  (shared with v2, re-exported so callers can use either engine alike)
    BANDS, EVIDENCE, ESTIMATED, HR_MIN_BINS, HR_MIN_COVERAGE, MEASURED, REFERENCE_MAX_WORKOUTS,
    REFERENCE_MIN_WORKOUTS, REFERENCE_WINDOW_DAYS, RELIABILITY, STRONG_COVERAGE, STRONG_MIN_BINS,
    STRONG_MIN_INDEX, STRONG_MIN_SAMPLES, UNAVAILABLE, D, DaySweat, Factor, HeartSummary, Item, Line,
    SweatSheet, effective_minutes, evidence_index, final_multiplier, heart_summary, qualifies_for_heart,
    reliability, score, speed_kmh,
)

RULES_VERSION = "proof-of-sweat-v3"
TEMPLATE = "proof_of_sweat_v3"  # stored on challenges.template
SUMMARY = ("About 1 Sweat Point per Oura-verified minute, raised by up to half for harder sessions, "
           "in proportion to the evidence behind them. Each day's first hour counts in full, then less.")

# ---- Effort factors, each centred on 1.00 ----
PROVIDER_FACTOR = {"easy": D("0.85"), "moderate": D("1.00"), "hard": D("1.30")}  # Oura's own intensity label

# Heart rate relative to the player's own reference: a session 10% above their usual level gives 1.30.
HR_SLOPE = D("3.00")  # factor = 1 + slope * (session median / reference median - 1)
HR_RANGE = (D("0.80"), D("1.65"))

# Average speed bands in km/h per category, (lower bound, factor), lowest first. Walking and hiking top
# out lower: a fast walk is not the effort of a fast run. Categories not listed have no movement signal.
MOVEMENT_BANDS: dict[str, tuple[tuple[float, Decimal], ...]] = {
    "run": ((0, D("0.90")), (8, D("1.00")), (10, D("1.20")), (12, D("1.45"))),
    "walk": ((0, D("0.90")), (4, D("1.00")), (5.5, D("1.15")), (6.5, D("1.30"))),
    "hike": ((0, D("0.95")), (3, D("1.00")), (4.5, D("1.20"))),
    "ride": ((0, D("0.90")), (15, D("1.00")), (22, D("1.20")), (28, D("1.45"))),
    "swim": ((0, D("0.90")), (1.5, D("1.00")), (2.5, D("1.20")), (3.2, D("1.45"))),
}

WEIGHTS = {"heart": D("0.45"), "movement": D("0.30"), "provider": D("0.25")}
MULTIPLIER_RANGE = (D("0.85"), D("1.50"))


def rules() -> dict:
    """Every number this version scores with, including the ones shared with v2. Its hash is what a challenge locks."""
    return {
        "version": RULES_VERSION,
        "gates": sweat.rules(),  # v1's mandatory checks, exactly
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
        "final": "base + base * (multiplier - 1) * reliability",
        "reliability": [[low, str(share)] for low, share in RELIABILITY],
        "evidence_index": EVIDENCE,
        "strong_evidence": {"min_index": STRONG_MIN_INDEX, "min_samples": STRONG_MIN_SAMPLES,
                            "min_bins": STRONG_MIN_BINS, "min_coverage": STRONG_COVERAGE},
    }


def rules_fingerprint() -> str:
    """SHA-256 (hex) of the rules, written as compact JSON with sorted keys."""
    return hashlib.sha256(json.dumps(rules(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def personal_reference(medians: list[int]) -> dict | None:
    """Same reference as v2 (median of 4-10 earlier workouts' medians), labelled with this version."""
    reference = sweat2.personal_reference(medians)
    return {**reference, "version": RULES_VERSION} if reference else None


def provider_factor(intensity: str | None) -> Factor:
    """Oura's own intensity label: an estimate, never shown as a measurement."""
    if intensity in PROVIDER_FACTOR:
        return Factor(PROVIDER_FACTOR[intensity], ESTIMATED, intensity)
    return Factor(D("1.00"), UNAVAILABLE, "no_intensity")


def heart_factor(heart: HeartSummary | None, reference: dict | None) -> Factor:
    """Effort relative to the player's own reference: 1 + 3 x (session / reference - 1), kept in [0.80, 1.65].

    Linear and monotonic. Neutral, with the reason, whenever the session's heart rate or the
    reference is not good enough to trust. Never an absolute bpm rule.
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


def movement_factor(category: str | None, distance_km: float | None, minutes: float) -> Factor:
    """Pace within the activity's own bands, for categories where distance means something. Otherwise neutral."""
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
