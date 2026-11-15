"""Shared storage for the two sources whose activities are entered through our own app."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import db
from fitness.base import Activity, FitnessProvider


class LoggedProvider(FitnessProvider):
    device: str | None = None
    is_manual = True

    def _to_activity(self, row: db.LoggedActivity) -> Activity:
        return Activity(
            id=f"{self.name}:{row.id}",
            type=row.type,
            start=db.utc(row.start_time),
            minutes=row.minutes,
            distance_km=row.distance_km,
            device=row.device,
            is_manual=self.is_manual,
        )

    def fetch_activities(self, session: Session, user_id: int, start: datetime, end: datetime) -> list[Activity]:
        rows = session.scalars(
            select(db.LoggedActivity)
            .where(
                db.LoggedActivity.user_id == user_id,
                db.LoggedActivity.source == self.name,
                db.LoggedActivity.start_time >= db.utc(start),
                db.LoggedActivity.start_time < db.utc(end),
            )
            .order_by(db.LoggedActivity.start_time, db.LoggedActivity.id)
        )
        return [self._to_activity(row) for row in rows]

    def log_activity(
        self, session: Session, user_id: int, type: str, start: datetime, minutes: float, distance_km: float
    ) -> Activity:
        row = db.LoggedActivity(
            user_id=user_id, source=self.name, type=type, start_time=db.utc(start),
            minutes=minutes, distance_km=distance_km, device=self.device,
        )
        session.add(row)
        session.commit()
        return self._to_activity(row)

    def disconnect(self, session: Session, user_id: int) -> None:
        session.execute(
            delete(db.LoggedActivity).where(
                db.LoggedActivity.user_id == user_id, db.LoggedActivity.source == self.name
            )
        )
