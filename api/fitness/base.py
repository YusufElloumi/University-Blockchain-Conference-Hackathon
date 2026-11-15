"""The one shape every fitness source must fit.

The rest of the API only ever sees `Activity` objects and the `FitnessProvider` methods, so
swapping mock, manual, or Strava changes nothing outside this folder.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

ACTIVITY_TYPES = ("run", "walk", "hike", "ride", "swim", "workout")


@dataclass(frozen=True)
class Activity:
    id: str  # unique within its provider, e.g. "mock:12"
    type: str  # one of ACTIVITY_TYPES
    start: datetime  # timezone-aware UTC
    minutes: float  # active time
    distance_km: float  # 0 when the activity has no distance
    device: str | None  # the watch or app that recorded it; None when typed in by hand
    is_manual: bool  # typed in by hand rather than recorded


class NotSupported(Exception):
    """The current provider cannot do this (the message is safe to show to the user)."""


class FitnessProvider(ABC):
    name: str
    counts_manual = False  # do hand-typed activities earn points?
    requires_device = False  # must an activity name the device that recorded it?
    label = ""  # shown next to activities in the app

    def connect_url(self, user_id: int) -> str | None:
        """Where to send the user to link their account. None when there is nothing to link."""
        return None

    def handle_callback(self, session: Session, user_id: int, params: dict) -> None:
        """Finishes linking after the outside service sends the user back to us."""
        raise NotSupported(f"The {self.name} source has no account to link.")

    @abstractmethod
    def fetch_activities(self, session: Session, user_id: int, start: datetime, end: datetime) -> list[Activity]:
        """The user's activities that started at or after `start` and before `end`."""

    def log_activity(
        self, session: Session, user_id: int, type: str, start: datetime, minutes: float, distance_km: float
    ) -> Activity:
        """Adds an activity entered through our app. Only some providers allow it."""
        raise NotSupported(f"Activities come from {self.name}; they cannot be added by hand.")

    @abstractmethod
    def disconnect(self, session: Session, user_id: int) -> None:
        """Unlinks the user and deletes everything this provider stored about them. Does not commit."""
