"""Fitness data sources. The rest of the API calls `get_provider()` and nothing else in here.

Set FITNESS_PROVIDER in .env to `mock` (default), `manual`, or `strava`.
Strava code, when it exists, lives only in this folder (see docs/STRAVA_FLOW.md).
"""

from __future__ import annotations

import config
from fitness.base import ACTIVITY_TYPES, Activity, FitnessProvider, NotSupported
from fitness.logged import LoggedProvider
from fitness.manual import ManualProvider
from fitness.mock import MockProvider

__all__ = ["ACTIVITY_TYPES", "Activity", "FitnessProvider", "LoggedProvider", "NotSupported", "get_provider"]

_PROVIDERS = {"mock": MockProvider, "manual": ManualProvider}


def get_provider(name: str | None = None) -> FitnessProvider:
    name = (name or config.FITNESS_PROVIDER).lower()
    if name == "strava":
        # Needs a Strava subscription to create an API app; nobody on the team has one yet.
        raise NotSupported("The Strava source is not set up. Use FITNESS_PROVIDER=mock or manual.")
    if name not in _PROVIDERS:
        raise NotSupported(f"Unknown FITNESS_PROVIDER '{name}'. Use mock, manual, or strava.")
    return _PROVIDERS[name]()
