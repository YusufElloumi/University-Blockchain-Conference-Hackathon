"""Mock source for demos and tests: pretends each activity was recorded on a watch."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from fitness.base import Activity
from fitness.logged import LoggedProvider

# A believable week: (day, hour of that day, type, minutes, km). Day 3 is a rest day.
SAMPLE_WEEK = [
    (0, 7, "run", 32, 5.4),
    (1, 18, "walk", 25, 2.1),
    (2, 7, "ride", 55, 18.0),
    (4, 12, "run", 28, 5.1),
    (5, 9, "hike", 90, 7.5),
    (6, 8, "run", 15, 2.5),
]


class MockProvider(LoggedProvider):
    name = "mock"
    label = "Demo data"
    device = "Mock Watch"
    is_manual = False

    def add_script(
        self, session: Session, user_id: int, challenge_start: datetime, script=SAMPLE_WEEK
    ) -> list[Activity]:
        """Adds a scripted set of activities, placed relative to the start of a challenge."""
        return [
            self.log_activity(session, user_id, type, challenge_start + timedelta(days=day, hours=hour), minutes, km)
            for day, hour, type, minutes, km in script
        ]
