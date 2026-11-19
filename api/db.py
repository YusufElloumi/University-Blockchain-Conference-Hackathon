"""Database setup and tables. SQLite locally, Postgres when deployed (same code through SQLAlchemy).

Twelve tables: the six in the plan, plus `logged_activities` (activities typed into our own app by
the mock and manual sources; Strava activities are never stored there), `invites` (who has redeemed
the invite code of a league or private event),
`pick_rounds` and `round_picks` (prediction rounds on Gemini markets), and `league_stats` (rows of a
league's stat sheet, uploaded by the organizer), and `oauth_states` (attempts to connect an outside
account such as Oura, each bound to one user, short-lived and single-use).

A database made before Nov 17 may still hold an unused `picks` table from the old pick'em tiebreaker
(removed: Gemini is only used through prediction rounds, and ties always split). It is left alone.

Times are stored in UTC. SQLite hands them back without a timezone, so read them through `utc()`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import BigInteger, ForeignKey, Text, UniqueConstraint, create_engine, inspect, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

import config

engine = create_engine(
    config.DATABASE_URL,
    # Postgres: keep every connection on UTC, because our columns store times without a timezone.
    connect_args={"check_same_thread": False} if config.DATABASE_URL.startswith("sqlite") else {"options": "-c timezone=utc"},
    pool_pre_ping=True,  # a free database drops idle connections; check before using one
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
    """A user's link to an outside fitness service (Oura; Strava later). Not used by the mock and manual sources.

    Tokens are encrypted with api/secretbox.py and never leave the server.
    """

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
    scopes: Mapped[str | None]  # permissions granted, space-separated, e.g. "workout heartrate"


class OAuthState(Base):
    """One "connect an outside account" attempt, from pressing Connect to finishing (api/fitness/oura.py).

    Binds the attempt to the Rival user who started it. Only a hash of the `state` value is stored.
    Expires after a few minutes and can be finished once.
    """

    __tablename__ = "oauth_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str] = mapped_column(unique=True, index=True)  # SHA-256 of the state, hex
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str]
    code_verifier_enc: Mapped[str | None] = mapped_column(Text)  # PKCE secret, encrypted; cleared after use
    code_enc: Mapped[str | None] = mapped_column(Text)  # the provider's one-time code, encrypted; cleared after use
    return_to: Mapped[str]  # the web app page to send the browser back to (checked against WEB_ORIGIN)
    created_at: Mapped[datetime] = mapped_column(default=_now)
    expires_at: Mapped[datetime]
    returned_at: Mapped[datetime | None]  # the provider sent the browser back
    used_at: Mapped[datetime | None]  # finished (or cancelled); never usable again


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
    # Play mode, off-chain only: "league", "public" or "private". Older rows have none and count as private.
    mode: Mapped[str | None] = mapped_column(default="private")
    organizer_name: Mapped[str | None]  # league events: the gym, club or tournament hosting it
    creator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(default=_now)
    settle_tx: Mapped[str | None]  # the transaction that paid out or refunded
    score_sheet: Mapped[str | None] = mapped_column(Text)  # final points as JSON; its hash is stored onchain
    attestation: Mapped[str | None] = mapped_column(Text)  # Proof of Effort JSON (attest.py); offchain only
    # Where the main points come from: None or "fitness" (players log workouts), or "league_stats" (league only).
    scoring_source: Mapped[str | None]
    stat_weights: Mapped[str | None] = mapped_column(Text)  # JSON {"goals": 2, "assists": 1, "points": 0}
    pick_themes: Mapped[str | None] = mapped_column(Text)  # JSON list of prediction round themes; empty = off
    round_hours: Mapped[int | None]  # a new prediction round every this many hours (24 or 168)
    # Competition format (see formats.py): winner_takes_all, podium, goal or teams. None = winner takes all.
    format: Mapped[str | None]
    format_config: Mapped[str | None] = mapped_column(Text)  # JSON settings of the format, fixed at creation


class Participant(Base):
    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("challenge_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    deposit_tx: Mapped[str | None]
    consent_at: Mapped[datetime]  # when they agreed to share their points with this group
    stat_name: Mapped[str | None]  # league stats: this player's name on the uploaded stat sheet
    team: Mapped[int | None]  # teams format: index of the team they picked when joining
    joined_at: Mapped[datetime] = mapped_column(default=_now)


class Invite(Base):
    """Someone who entered the invite code of a league or private event, so they may see and join it."""

    __tablename__ = "invites"
    __table_args__ = (UniqueConstraint("challenge_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(default=_now)


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


class PickRound(Base):
    """One prediction round: the Gemini market chosen for it, and its result once known."""

    __tablename__ = "pick_rounds"
    __table_args__ = (UniqueConstraint("challenge_id", "number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    number: Mapped[int]  # 0 = the first round
    event_ticker: Mapped[str]  # Gemini's ID for the event
    event_title: Mapped[str]
    theme: Mapped[str]
    league: Mapped[str]
    options: Mapped[str] = mapped_column(Text)  # JSON [{id, label, chance}] when the round opened
    locks_at: Mapped[datetime]  # kick-off: picks close
    expected_end: Mapped[datetime]  # when the result should be in
    status: Mapped[str] = mapped_column(default="open")  # open, resolved, void
    winning_option_id: Mapped[str | None]
    checked_at: Mapped[datetime | None]  # last time we asked Gemini for the result
    resolved_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=_now)


class RoundPick(Base):
    """A player's pick in one prediction round, with the market's probability when they made it."""

    __tablename__ = "round_picks"
    __table_args__ = (UniqueConstraint("round_id", "user_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    round_id: Mapped[int] = mapped_column(ForeignKey("pick_rounds.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    option_id: Mapped[str]
    option_label: Mapped[str]
    probability: Mapped[float]  # 0 to 1, locked when the pick was made
    points: Mapped[float | None]  # None until the round is resolved
    picked_at: Mapped[datetime] = mapped_column(default=_now)


class LeagueStat(Base):
    """One row of a league's stat sheet: one player in one game. Uploaded by the organizer as CSV."""

    __tablename__ = "league_stats"

    id: Mapped[int] = mapped_column(primary_key=True)
    challenge_id: Mapped[int] = mapped_column(ForeignKey("challenges.id"), index=True)
    game_date: Mapped[str]  # YYYY-MM-DD
    player_name: Mapped[str]
    jersey_number: Mapped[str | None]
    team: Mapped[str | None]
    goals: Mapped[int] = mapped_column(default=0)
    assists: Mapped[int] = mapped_column(default=0)
    points: Mapped[int | None]  # the sheet's own points column, if it has one
    uploaded_at: Mapped[datetime] = mapped_column(default=_now)


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
    with engine.begin() as connection:  # events from before play modes existed are private
        connection.execute(update(Challenge).where(Challenge.mode.is_(None)).values(mode="private"))


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
