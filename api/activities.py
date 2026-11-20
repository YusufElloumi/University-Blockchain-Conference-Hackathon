"""Which activities count in a challenge: "all exercise" or one sport. Pure, no database, no network.

A challenge creator picks one option on the create screen. Anything other than "all" is written into
the challenge's ruleset (api/rules.py) as the exact list of Oura activity names that count, so the
restriction is covered by the rules hash locked onchain and cannot change after creation. Scoring
reads the list from the stored ruleset, never from this file, so editing the lists below can never
change a challenge that already exists.

Oura reports each workout's type as a free-text `activity` name (for example "running" or
"strengthTraining"). Names are compared in lower case with punctuation removed. A name that is not
listed is never guessed at: it does not count in a sport-specific challenge.

"All exercise" adds nothing to the ruleset and keeps the existing behaviour: every activity in the
curated list (fitness/oura_sync.ACTIVITY_MAP) counts.

The sport restriction is an eligibility rule on top of Proof of Sweat. It never replaces a check:
a matching workout must still pass every mandatory check (source, timing, duration, speed ceiling,
duplicates) before it scores.
"""

from __future__ import annotations

import re

VERSION = "activities-v1"
ALL = "all"

# Oura activity names per sport, normalized (lower case, letters and digits only).
# Each list must stay inside the curated list in fitness/oura_sync.ACTIVITY_MAP (a test checks it).
SPORTS: dict[str, tuple[str, ...]] = {
    "running": ("running", "run", "treadmill", "trailrunning", "jogging", "indoorrunning", "outdoorrunning"),
    "walking": ("walking", "walk", "indoorwalking", "outdoorwalking", "nordicwalking", "powerwalking"),
    "hiking": ("hiking", "hike", "trekking", "mountaineering", "backpacking"),
    "cycling": ("cycling", "indoorcycling", "outdoorcycling", "biking", "mountainbiking", "roadcycling", "spinning",
                "ebiking", "bicycling"),
    "strength": ("strengthtraining", "weighttraining", "weightlifting", "functionaltraining",
                 "functionalstrengthtraining", "corestrength", "coretraining", "calisthenics", "trx"),
}
CHOICES = (ALL, *SPORTS)
LABELS = {ALL: "All exercise", "running": "Running", "walking": "Walking", "hiking": "Hiking",
          "cycling": "Cycling", "strength": "Strength training"}
REASON = "activity_not_in_challenge"  # shown on a receipt when a workout is a different sport


class ActivityError(ValueError):
    """A selection that cannot be used (the message is safe to show)."""


def normalize(provider_activity) -> str | None:
    if not isinstance(provider_activity, str):
        return None
    return re.sub(r"[^a-z0-9]", "", provider_activity.lower()) or None


def sport_of(provider_activity) -> str | None:
    """The sport an Oura activity name belongs to, or None (general exercise, or not listed)."""
    name = normalize(provider_activity)
    return next((sport for sport, names in SPORTS.items() if name in names), None)


def locked(selection: str | None) -> dict | None:
    """What goes into the ruleset. None for "all exercise", so those rulesets are unchanged."""
    selection = selection or ALL
    if selection not in CHOICES:
        raise ActivityError("Choose which activities count: all exercise, or one sport.")
    if selection == ALL:
        return None
    return {"selection": selection, "label": LABELS[selection], "version": VERSION, "provider": "oura",
            "oura_activities": sorted(SPORTS[selection])}


def selection_of(ruleset: dict | None) -> str:
    """The selection a ruleset locked. "all" when it has none (including every older challenge)."""
    return ((ruleset or {}).get("activities") or {}).get("selection") or ALL


def counts(ruleset: dict | None, provider_activity) -> bool:
    """Whether a workout's Oura activity is one this challenge counts, by the challenge's own locked list."""
    restriction = (ruleset or {}).get("activities")
    if not restriction:
        return True
    return normalize(provider_activity) in restriction["oura_activities"]


def view(ruleset: dict | None) -> dict:
    """For API replies: the selection and its label."""
    selection = selection_of(ruleset)
    return {"selection": selection, "label": LABELS.get(selection, selection), "restricted": selection != ALL}
