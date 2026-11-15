"""Database setup and tables. SQLite locally, Postgres when deployed (same code through SQLAlchemy).

Eight tables: the six in the plan, plus `logged_activities` (activities typed into our own app by
the mock and manual sources; Strava activities are never stored there) and `picks` (the pick'em
tiebreaker).

Times are stored in UTC. SQLite hands them back without a timezone, so read them through `utc()`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, ForeignKey, Text, UniqueConstraint, create_engine, inspect, text, update
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


def utc(value: datetime) -> datetime:
    """A datetime as timezone-aware UTC (database values come back without a timezone on SQLite)."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FitnessConnection(Base):
    """A user's link to an outside fitness service (Strava). Not used by the mock and manual sources."""

    __tablename__ = "fitness_connections"
    __table_args__ = (UniqueConstraint("user_id", "provider"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str]
    athlete_id: Mapped[str | None]
    access_token_enc: Mapped[str | None] = mapped_column(Text)  # encrypted, never plain text
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    token_expires_at: Mapped[datetime | None]
    connected_at: Mapped[datetime] = mapped_column(default=_now)


class Challenge(Base):
    """Our record of a challenge that exists onchain. The money and the player list live onchain."""

    __tablename__ = "challenges"

    id: Mapped[int] = mapped_column(primary_key=True)
    address: Mapped[str] = mapped_column(unique=True, index=True)  # the onchain challenge account
    name: Mapped[str]
    template: Mapped[str] = mapped_column(default="daily_mover")  # which scoring rules apply
    buy_in_units: Mapped[int] = mapped_column(BigInteger)  # USDC in its smallest unit (1 USDC = 1,000,000)
    start_time: Mapped[datetime]
    end_time: Mapped[datetime]
    status: Mapped[str] = mapped_column(default="open")  # open, settled, refunded (mirrors the program)
    invite_code: Mapped[str] = mapped_column(unique=True, index=True)
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    settle_tx: Mapped[str | None]  # the transaction that paid out or refunded
    score_sheet: Mapped[str | None] = mapped_column(Text)  # final points as JSON; its hash is stored onchain


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("challenge_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deposit_tx: Mapped[str | None]
    consent_at: Mapped[datetime]  # when they agreed to share their points with this group
    joined_at: Mapped[datetime] = mapped_column(default=_now)


class ScoreEntry(Base):
    """One player's points for one day of one challenge. Points and activity IDs only, no activity details."""

    __tablename__ = "score_entries"
    __table_args__ = (UniqueConstraint("challenge_id", "user_id", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    day: Mapped[int]  # 0 = the first 24 hours after the challenge starts, 1 = the next 24, ...
    points: Mapped[int]
    active: Mapped[bool]  # the "daily tick": enough active minutes that day
    source: Mapped[str]  # which fitness provider the points came from
    source_activity_ids: Mapped[str] = mapped_column(Text)  # JSON list of the activities that counted
    updated_at: Mapped[datetime] = mapped_column(default=_now)


class Pick(Base):
    """A player's one free tiebreaker pick for a challenge: which side wins a game listed on Gemini."""

    __tablename__ = "picks"
    __table_args__ = (UniqueConstraint("challenge_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    event_ticker: Mapped[str]  # Gemini's ID for the game
    event_title: Mapped[str]
    option_id: Mapped[str]  # Gemini's ID for the side picked
    option_label: Mapped[str]
    chance: Mapped[int | None]  # the market's chance for that side when the pick was made, in percent
    created_at: Mapped[datetime] = mapped_column(default=_now)


class LoggedActivity(Base):
    """An activity entered through our own app (mock or manual source)."""

    __tablename__ = "logged_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source: Mapped[str]  # "mock" or "manual"
    type: Mapped[str]
    start_time: Mapped[datetime]
    minutes: Mapped[float]
    distance_km: Mapped[float]
    device: Mapped[str | None]
    created_at: Mapped[datetime] = mapped_column(default=_now)


def init_db() -> None:
    Base.metadata.create_all(engine)
    _add_missing_columns()


def _add_missing_columns() -> None:
    """Adds columns that were introduced after a table was first created (create_all never alters tables).

    Only handles new optional columns, which is all we have needed so far.
    """
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table in Base.metadata.sorted_tables:
            existing = {column["name"] for column in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name not in existing and column.nullable:
                    kind = column.type.compile(engine.dialect)
                    connection.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {kind}'))


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
