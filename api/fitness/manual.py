"""Manual source: the user types in what they did. Nothing checks it, so the app labels it unverified."""

from __future__ import annotations

from fitness.logged import LoggedProvider


class ManualProvider(LoggedProvider):
    name = "manual"
    label = "Self-reported (unverified)"
    counts_manual = True
    device = None
    is_manual = True
