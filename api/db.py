"""Database setup and tables. SQLite locally, Postgres when deployed (same code through SQLAlchemy).

`users` and `chain_events` exist so far; the other four tables arrive in Stage 4.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Text, UniqueConstraint, create_engine, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import config

engine = create_engine(
    config.DATABASE_URL,
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    privy_id: Mapped[str] = mapped_column(unique=True, index=True)
    email: Mapped[str | None]
    display_name: Mapped[str | None]
    wallet_address: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    gas_drips: Mapped[int] = mapped_column(default=0)  # how many times we sent this wallet fee money
    funded_at: Mapped[datetime | None]  # when "Add test funds" was used (once per user)
    funded_tx: Mapped[str | None]


class ChainEvent(Base):
    """One event emitted by our program, as delivered by the QuickNode Stream."""

    __tablename__ = "chain_events"
    __table_args__ = (UniqueConstraint("signature", "event_index"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    signature: Mapped[str] = mapped_column(index=True)  # the transaction it happened in
    event_index: Mapped[int]  # position among our events in that transaction
    name: Mapped[str]  # ChallengeCreated, PlayerJoined, ChallengeEnded, ChallengeSettled, ChallengeRefunded
    challenge: Mapped[str | None] = mapped_column(index=True)
    slot: Mapped[int | None]
    block_time: Mapped[datetime | None]
    data: Mapped[str] = mapped_column(Text)  # the event's fields as JSON
    received_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))


def init_db() -> None:
    Base.metadata.create_all(engine)


def get_session():
    """FastAPI dependency: one database session per request."""
    with SessionLocal() as session:
        yield session


def claim_test_funds(session: Session, user_id: int) -> bool:
    """Marks the user as funded. Returns False if they already were (safe against double clicks)."""
    result = session.execute(
        update(User)
        .where(User.id == user_id, User.funded_at.is_(None))
        .values(funded_at=datetime.now(timezone.utc))
    )
    session.commit()
    return result.rowcount == 1


def release_test_funds(session: Session, user_id: int) -> None:
    """Undoes claim_test_funds when the transfer failed, so the user can try again."""
    session.execute(update(User).where(User.id == user_id).values(funded_at=None, funded_tx=None))
    session.commit()
