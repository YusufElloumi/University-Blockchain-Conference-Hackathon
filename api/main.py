"""Loser Buys API. Run from api/:  uvicorn main:app --reload

Stage 2 endpoints (all need the Privy login token in "Authorization: Bearer <token>"):
    POST /me/setup   save the user, and quietly send their wallet fee money if it is low
    POST /me/fund    "Add test funds": send devnet USDC once per user

Stage 3 endpoints:
    POST /webhooks/quicknode            onchain events delivered by the QuickNode Stream (signature checked)
    GET  /challenges/{address}/events   the stored events for one challenge (public onchain data)

Stage 4 endpoints (all need the login token):
    POST   /challenges                        record a challenge that was just created onchain
    POST   /challenges/{address}/join         record a player after their deposit, with their consent to share points
    GET    /challenges/{address}/leaderboard  points and daily ticks; players of that challenge only
    POST   /me/activities                     add an activity (mock and manual sources) and update points
    GET    /me/activities                     the caller's own activities; never anyone else's
    DELETE /me/fitness                        disconnect: delete the caller's fitness data and points

Stage 5 endpoints:
    GET  /app-config                    public settings for the web app (oracle address, fitness source)
    POST /me/name                       set the name other players see
    GET  /me/challenges                 challenges the caller joined or created
    GET  /challenges/{address}/state    the whole challenge screen in one call: feed, pool, deposit status, leaderboard

Stage 6 endpoints:
    POST /challenges/{address}/finish          pay the winner or refund, whichever is due (players)
    POST /admin/challenges/{address}/end-now   "End week now" (admin emails from ADMIN_EMAILS)
    POST /internal/tick                        finish everything that is due (scheduler, X-Tick-Secret header)
    GET  /challenges/{address}/score-sheet     final points and the hash stored onchain (players)

Prediction rounds (one Gemini market per round; a right pick earns 1 / probability points, max 5):
    POST /challenges/{address}/rounds/{number}/pick   the caller's pick in a round, changeable until kick-off
League stats (league events scored from the league's stat sheet, uploaded as CSV by the organizer):
    GET  /stats/template.csv                 the CSV template
    GET  /challenges/{address}/stats         uploaded dates, sheet names and matching (organizer)
    POST /challenges/{address}/stats         upload CSV text (organizer)
    POST /challenges/{address}/stats/match   link players to sheet names (organizer)
Play modes (league, public, private; off-chain only):
    GET  /events/public                 open public events anyone can join
    POST /invites/redeem                enter a league or private event's invite code to see and join it
    GET  /me/challenges?mode=           also lists events the caller was invited to
Oura connection (OAuth only; no Oura data is read yet; see api/fitness/oura.py):
    GET    /integrations/oura            is Oura available, and is the caller connected
    POST   /integrations/oura/start      begin connecting: returns Oura's sign-in address
    GET    /integrations/oura/callback   Oura sends the browser here (no login); parks the code, returns to the web app
    POST   /integrations/oura/complete   finish connecting as the signed-in user; tokens stay on the server
    DELETE /integrations/oura            revoke at Oura where possible and delete the stored tokens
    GET    /integrations/oura/workouts   read-only test: the caller's recent Oura workouts and heart-rate coverage (nothing stored)
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

import json

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, Field
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import attest
import config
import auth
import chain
import db
import events
import formats
import fitness
from fitness import oura, oura_data
import leaguestats
import pickrounds
import scores
import scoring
import secretbox
import settlement
import treasury

log = logging.getLogger("loser_buys")


class _HideOAuthQuery(logging.Filter):
    """Keeps Oura's one-time code and state out of the server's request log."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and str(args[2]).startswith("/integrations/oura/callback?"):
            record.args = (*args[:2], "/integrations/oura/callback?[hidden]", *args[3:])
        return True


logging.getLogger("uvicorn.access").addFilter(_HideOAuthQuery())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="Loser Buys API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


def current_user(
    privy_id: str = Depends(auth.current_privy_id), session: Session = Depends(db.get_session)
) -> db.User:
    """The logged-in user's database row, created on first sight. Looks up their wallet from Privy."""
    user = session.scalar(select(db.User).where(db.User.privy_id == privy_id))
    if user is None:
        user = db.User(privy_id=privy_id)
        session.add(user)
    if not user.wallet_address:
        try:
            profile = auth.fetch_privy_user(privy_id)
        except Exception as e:
            log.exception("Privy user lookup failed")
            raise HTTPException(502, "Could not reach the login provider") from e
        user.email = profile.email
        user.wallet_address = profile.wallet
    session.commit()
    if not user.wallet_address:
        # Privy creates the wallet a moment after the first login; the web app retries.
        raise HTTPException(409, "Your account is still being set up. Try again in a moment.")
    return user


def _is_admin(user: db.User) -> bool:
    return bool(user.email) and user.email.lower() in config.ADMIN_EMAILS


def _user_view(user: db.User, usdc_units: int | None = None) -> dict:
    return {
        "wallet": user.wallet_address,
        "email": user.email,
        "name": scores.display_name(user),
        "is_admin": _is_admin(user),
        "test_funds_used": user.funded_at is not None,
        "test_funds_amount": config.TEST_FUNDS_UNITS / 10**config.USDC_DECIMALS,
        "usdc": None if usdc_units is None else usdc_units / 10**config.USDC_DECIMALS,
    }


@app.get("/health")
def health() -> dict:
    return {"ok": True, "network": "devnet"}


@app.post("/me/setup")
def setup(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """Called by the web app after login. Tops up fee money (the user never sees it)."""
    wallet = Pubkey.from_string(user.wallet_address)
    gas_ready = True
    try:
        if treasury.sol_balance(wallet) < config.GAS_LOW_LAMPORTS:
            if user.gas_drips >= config.GAS_DRIP_MAX_PER_USER:
                gas_ready = False
            else:
                user.gas_drips += 1
                session.commit()
                treasury.send_gas(wallet)
        usdc = treasury.usdc_balance(wallet)
    except Exception as e:
        log.exception("Gas drip failed")
        raise HTTPException(503, "The network is busy. Try again in a moment.") from e
    return {**_user_view(user, usdc), "ready": gas_ready}


@app.post("/me/fund")
def fund(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """ "Add test funds": sends devnet USDC from the treasury. Once per user."""
    if not db.claim_test_funds(session, user.id):
        raise HTTPException(409, "Devnet USDC was already added to this account.")
    wallet = Pubkey.from_string(user.wallet_address)
    try:
        signature = treasury.send_usdc(wallet)
    except TimeoutError as e:
        # The transfer may still land, so the claim stays in place rather than risk paying twice.
        log.exception("Test funds transfer not confirmed")
        raise HTTPException(504, "This is taking longer than usual. Check your balance in a minute.") from e
    except Exception as e:
        log.exception("Test funds transfer failed")
        db.release_test_funds(session, user.id)
        raise HTTPException(503, "Could not add devnet USDC right now. Try again in a moment.") from e
    session.refresh(user)
    user.funded_tx = signature
    session.commit()
    return {**_user_view(user, treasury.usdc_balance(wallet)), "signature": signature}


@app.post("/webhooks/quicknode")
async def quicknode_webhook(request: Request, session: Session = Depends(db.get_session)) -> dict:
    """The QuickNode Stream calls this for every block that contains a transaction for our program."""
    if not config.QUICKNODE_STREAM_SECURITY_TOKEN:
        raise HTTPException(503, "QUICKNODE_STREAM_SECURITY_TOKEN is not set on the server")
    if not any(request.headers.get(h) for h in ("x-qn-nonce", "x-qn-timestamp", "x-qn-signature")):
        # QuickNode's "Check Connection" button sends an unsigned test request. Say hello, store nothing.
        return {"status": "ok", "new_events": 0}
    try:
        body = events.decode_body(await request.body(), request.headers.get("content-encoding"))
        events.verify_delivery(
            config.QUICKNODE_STREAM_SECURITY_TOKEN,
            body,
            request.headers.get("x-qn-nonce"),
            request.headers.get("x-qn-timestamp"),
            request.headers.get("x-qn-signature"),
        )
    except (events.BadSignature, OSError) as e:
        raise HTTPException(401, f"Rejected: {e}") from e
    try:
        payload = json.loads(body) if body.strip() else None
    except ValueError as e:
        raise HTTPException(400, "Body is not JSON") from e
    stored = events.store_delivery(session, payload)
    if stored:
        log.info("Stored %d onchain event(s) from the Stream", stored)
    return {"status": "received", "new_events": stored}


@app.get("/challenges/{address}/events")
def challenge_events(address: str, session: Session = Depends(db.get_session)) -> list[dict]:
    rows = session.scalars(
        select(db.ChainEvent).where(db.ChainEvent.challenge == address).order_by(db.ChainEvent.slot, db.ChainEvent.id)
    )
    return [
        {
            "name": row.name,
            "signature": row.signature,
            "slot": row.slot,
            "block_time": row.block_time.isoformat() if row.block_time else None,
            "data": json.loads(row.data),
        }
        for row in rows
    ]


# ---------- Stage 4: challenges, activities, points ----------


MODES = ("league", "public", "private")
MAX_PLAYERS = 8  # the program's limit per event (onchain/programs/loser_buys/src/constants.rs)
# Invite codes avoid look-alike characters (0/O, 1/I/L) so they are easy to read out and type.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


class NewChallenge(BaseModel):
    address: str
    name: str = Field(min_length=1, max_length=60)
    mode: Literal[MODES] = "private"  # type: ignore[valid-type]
    organizer_name: str | None = Field(default=None, max_length=60)  # required for league events
    scoring_source: Literal["fitness", "league_stats"] = "fitness"  # league_stats: league events only
    stat_weights: dict[Literal["goals", "assists", "points"], float] | None = None
    pick_themes: list[Literal[tuple(pickrounds.THEMES)]] = Field(default_factory=list)  # type: ignore[valid-type]
    round_hours: Literal[pickrounds.ROUND_CHOICES] | None = None  # type: ignore[valid-type]
    format: Literal[formats.FORMATS] = formats.DEFAULT_FORMAT  # type: ignore[valid-type]
    format_config: dict | None = None  # the format's settings; see formats.clean_config


class InviteCode(BaseModel):
    code: str = Field(min_length=1, max_length=40)


class JoinRecord(BaseModel):
    consent: bool  # "Share my challenge points with this group"
    deposit_tx: str | None = Field(default=None, max_length=100)
    team: int | None = Field(default=None, ge=0, le=1)  # teams format: which team they are joining


class NewActivity(BaseModel):
    type: Literal[fitness.ACTIVITY_TYPES]  # type: ignore[valid-type]
    minutes: float = Field(gt=0, le=24 * 60)
    distance_km: float = Field(default=0, ge=0, le=1000)
    start: datetime | None = None  # when it began; defaults to now


def onchain_challenge(address: str) -> chain.Challenge:
    """Reads the challenge account from Solana devnet. The chain is the source of truth for money and players."""
    try:
        key = Pubkey.from_string(address)
    except ValueError as e:
        raise HTTPException(400, "That is not a valid challenge address.") from e
    try:
        return chain.fetch_challenge(Client(chain.RPC_URL), key)
    except ValueError as e:
        raise HTTPException(404, "No challenge was found at that address.") from e
    except Exception as e:
        log.exception("Could not read the challenge from devnet")
        raise HTTPException(503, "The network is busy. Try again in a moment.") from e


def _stored_challenge(session: Session, address: str) -> db.Challenge:
    challenge = session.scalar(select(db.Challenge).where(db.Challenge.address == address))
    if challenge is None:
        raise HTTPException(404, "We do not know that challenge.")
    return challenge


def _is_player(session: Session, challenge: db.Challenge, user: db.User) -> bool:
    return session.scalar(
        select(db.Participant.id).where(
            db.Participant.challenge_id == challenge.id, db.Participant.user_id == user.id
        )
    ) is not None


def _mode(challenge: db.Challenge) -> str:
    return challenge.mode or "private"


def _is_invited(session: Session, challenge: db.Challenge, user: db.User) -> bool:
    return session.scalar(
        select(db.Invite.id).where(db.Invite.challenge_id == challenge.id, db.Invite.user_id == user.id)
    ) is not None


def _can_see(session: Session, challenge: db.Challenge, user: db.User) -> bool:
    """Public events are open to everyone. League and private events need an invite (or being in them)."""
    return (
        _mode(challenge) == "public"
        or challenge.creator_id == user.id
        or _is_player(session, challenge, user)
        or _is_invited(session, challenge, user)
    )


def _visible_challenge(session: Session, address: str, user: db.User) -> db.Challenge:
    """The stored challenge, or 404 if the caller may not see it (so an invite-only event is not even confirmed)."""
    challenge = _stored_challenge(session, address)
    if not _can_see(session, challenge, user):
        raise HTTPException(404, "We do not know that challenge.")
    return challenge


def _new_invite_code(session: Session) -> str:
    while True:
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if session.scalar(select(db.Challenge.id).where(db.Challenge.invite_code == code)) is None:
            return code


def _challenge_view(challenge: db.Challenge) -> dict:
    return {
        "address": challenge.address,
        "name": challenge.name,
        "mode": _mode(challenge),
        "organizer_name": challenge.organizer_name,
        "template": challenge.template,
        "buy_in": challenge.buy_in_units / 10**config.USDC_DECIMALS,
        "start": db.utc(challenge.start_time).isoformat(),
        "end": db.utc(challenge.end_time).isoformat(),
        "status": challenge.status,
        "invite_code": challenge.invite_code,
        "scoring_source": challenge.scoring_source or "fitness",
        "stat_weights": leaguestats.weights(challenge) if scores.uses_league_stats(challenge) else None,
        "pick_themes": pickrounds.settings(challenge)[0],
        "round_hours": pickrounds.settings(challenge)[1],
        "round_count": pickrounds.round_count(challenge),
        "format": formats.of(challenge)[0],
        "format_config": formats.of(challenge)[1],
        "format_summary": formats.describe(*formats.of(challenge)),
    }


def _activity_view(activity: fitness.Activity, provider: fitness.FitnessProvider) -> dict:
    return {
        "id": activity.id,
        "type": activity.type,
        "start": activity.start.isoformat(),
        "minutes": activity.minutes,
        "distance_km": activity.distance_km,
        "device": activity.device,
        "verified": not activity.is_manual,
        "source": provider.name,
        "source_label": provider.label,
    }


def _provider() -> fitness.FitnessProvider:
    try:
        return fitness.get_provider()
    except fitness.NotSupported as e:
        raise HTTPException(503, str(e)) from e


@app.post("/challenges")
def record_challenge(
    body: NewChallenge, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Called by the web app right after `create_challenge` lands. Details are read from the chain, not the browser."""
    existing = session.scalar(select(db.Challenge).where(db.Challenge.address == body.address))
    if existing is not None:
        return _challenge_view(existing)
    organizer = " ".join((body.organizer_name or "").split()) or None
    if body.mode == "league" and not organizer:
        raise HTTPException(400, "Enter the organizer's name for a league.")
    state = onchain_challenge(body.address)
    if str(state.creator) != user.wallet_address:
        raise HTTPException(403, "Only the person who created this challenge can set it up.")
    # Length is read from the chain, never from the browser.
    length = timedelta(seconds=state.end_time - state.start_time)
    if not scoring.MIN_LENGTH <= length <= scoring.MAX_LENGTH:
        raise HTTPException(400, "A challenge must run for at least 15 minutes and at most 365 days.")
    days = scoring.day_count(datetime.fromtimestamp(state.start_time, timezone.utc),
                             datetime.fromtimestamp(state.end_time, timezone.utc))
    if body.scoring_source == "league_stats" and body.mode != "league":
        raise HTTPException(400, "League stats scoring is for league events only.")
    if body.stat_weights and not all(0 <= v <= 10 for v in body.stat_weights.values()):
        raise HTTPException(400, "Stat weights must be between 0 and 10.")
    themes = list(dict.fromkeys(body.pick_themes))
    try:
        format_config = formats.clean_config(body.format, body.format_config,
                                             league_stats=body.scoring_source == "league_stats", days=days)
    except formats.FormatError as e:
        raise HTTPException(400, str(e)) from e
    if bool(themes) != bool(body.round_hours):
        raise HTTPException(400, "Choose at least one theme and how often a round opens, or turn picks off.")
    challenge = _register(
        session, body.address, state, body.name.strip(), user.id,
        mode=body.mode, organizer_name=organizer if body.mode == "league" else None,
    )
    if challenge.creator_id == user.id and challenge.scoring_source is None and challenge.pick_themes is None:
        challenge.scoring_source = body.scoring_source
        if body.scoring_source == "league_stats":
            challenge.stat_weights = json.dumps({**leaguestats.DEFAULT_WEIGHTS, **(body.stat_weights or {})})
        challenge.pick_themes = json.dumps(themes)
        challenge.round_hours = body.round_hours
        # The format is fixed here, before anyone else can join, and never changes afterwards.
        challenge.format = body.format
        challenge.format_config = json.dumps(format_config)
        session.commit()
    return _challenge_view(challenge)


def _register(
    session: Session, address: str, state: chain.Challenge, name: str, creator_id: int | None,
    mode: str = "private", organizer_name: str | None = None,
) -> db.Challenge:
    """Stores our record of an onchain challenge, after checking it is one this app can settle."""
    if str(state.oracle) != config.ORACLE_PUBLIC_KEY or str(state.mint) != config.USDC_MINT:
        raise HTTPException(400, "That challenge was not set up for this app.")
    challenge = db.Challenge(
        address=address,
        name=name,
        buy_in_units=state.buy_in,
        start_time=datetime.fromtimestamp(state.start_time, timezone.utc),
        end_time=datetime.fromtimestamp(state.end_time, timezone.utc),
        status=state.status,
        invite_code=_new_invite_code(session),
        creator_id=creator_id,
        mode=mode,
        organizer_name=organizer_name,
    )
    session.add(challenge)
    try:
        session.commit()
    except IntegrityError:  # a double click stored it a moment ago
        session.rollback()
        challenge = _stored_challenge(session, address)
    return challenge


@app.post("/challenges/{address}/join")
def record_join(
    address: str, body: JoinRecord, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Called after `join_challenge` lands. The player must agree to share points and be in the onchain player list."""
    if not body.consent:
        raise HTTPException(400, "To join, agree to share your challenge points with this group.")
    challenge = session.scalar(select(db.Challenge).where(db.Challenge.address == address))
    state = None
    if challenge is None:
        # Created outside the web app (for example by our demo script): record it on first join.
        # Nobody could have shared an invite code for it yet, so it is listed as a public event.
        state = onchain_challenge(address)
        challenge = _register(session, address, state, "Weekly challenge", None, mode="public")
    elif not _can_see(session, challenge, user):
        raise HTTPException(404, "We do not know that challenge.")
    if not _is_player(session, challenge, user):
        state = state or onchain_challenge(address)
        if user.wallet_address not in {str(p) for p in state.players}:
            raise HTTPException(409, "We have not seen your deposit yet. Try again in a moment.")
        session.add(
            db.Participant(
                challenge_id=challenge.id, user_id=user.id, deposit_tx=body.deposit_tx,
                consent_at=datetime.now(timezone.utc), team=_team_for(session, challenge, body.team),
            )
        )
        try:
            session.commit()
        except IntegrityError:  # a double click stored it a moment ago
            session.rollback()
        scores.recompute(session, challenge, user.id)
    return {"challenge": _challenge_view(challenge), "joined": True}


def _team_for(session: Session, challenge: db.Challenge, picked: int | None) -> int | None:
    """Teams format: the team the player picked, or (if they did not pick, e.g. our join script) the smaller one."""
    if formats.of(challenge)[0] != "teams":
        return None
    if picked is not None:
        return picked
    sizes = [0, 0]
    for team in session.scalars(select(db.Participant.team).where(db.Participant.challenge_id == challenge.id)):
        if team in (0, 1):
            sizes[team] += 1
    return 0 if sizes[0] <= sizes[1] else 1


@app.get("/challenges/{address}/leaderboard")
def challenge_leaderboard(
    address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Points and daily ticks only. Players agreed to share these with their group, so only the group sees them."""
    challenge = _visible_challenge(session, address, user)
    if not _is_player(session, challenge, user):
        raise HTTPException(403, "Join this challenge to see its leaderboard.")
    return {
        "challenge": _challenge_view(challenge),
        "players": [
            {"rank": r["rank"], "name": r["name"], "points": r["points"], "ticks": r["ticks"],
             "is_you": r["user_id"] == user.id}
            for r in scores.leaderboard(session, challenge)
        ],
    }


@app.post("/me/activities")
def add_activity(
    body: NewActivity, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Adds an activity for the caller, then updates their points in every challenge they are in."""
    provider = _provider()
    now = datetime.now(timezone.utc)
    # No start given: it counts from now, so a workout logged just after kick-off is inside the challenge.
    start = db.utc(body.start) if body.start else now
    if start > now:
        raise HTTPException(400, "An activity cannot start in the future.")
    try:
        activity = provider.log_activity(session, user.id, body.type, start, body.minutes, body.distance_km)
    except fitness.NotSupported as e:
        raise HTTPException(409, str(e)) from e
    results = []
    for challenge in scores.challenges_of(session, user.id):
        sheet = scores.recompute(session, challenge, user.id)
        if scores.uses_league_stats(challenge):
            results.append({"address": challenge.address, "name": challenge.name, "points": 0, "counted": False,
                            "reason": "this event is scored from the league's stat sheet"})
            continue
        counted = any(activity.id in day.activity_ids for day in sheet.days.values())
        results.append(
            {
                "address": challenge.address,
                "name": challenge.name,
                "points": sheet.total,
                "counted": counted,
                # Activities outside the dates are never fetched, so they have no recorded reason.
                "reason": None if counted else sheet.rejected.get(activity.id, "outside the challenge dates"),
            }
        )
    return {"activity": _activity_view(activity, provider), "challenges": results}


@app.get("/me/activities")
def my_activities(
    challenge: str | None = None, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> list[dict]:
    """The caller's own activities from the last 30 days, newest first. Only ever their own.

    With `?challenge=<address>` (a challenge the caller plays in), each activity also gets its
    state there: verified, flagged (typed in by hand) or rejected, with the reason.
    """
    provider = _provider()
    now = datetime.now(timezone.utc)
    activities = provider.fetch_activities(session, user.id, now - timedelta(days=30), now + timedelta(days=1))
    views = [_activity_view(a, provider) for a in reversed(activities)]
    if challenge:
        found = _visible_challenge(session, challenge, user)
        if _is_player(session, found, user) and not scores.uses_league_stats(found):
            sheet = scores.sheet_for(session, found, user.id)
            for view in views:
                view["status"], view["reason"] = sheet.verdict(view["id"])
    return views


# ---------- Stage 5: what the screens need ----------


class NewName(BaseModel):
    name: str = Field(min_length=1, max_length=24)


@app.get("/app-config")
def app_config() -> dict:
    """Public settings the web app needs before it can create a challenge or show the activity form."""
    provider = _provider()
    return {
        "oracle": config.ORACLE_PUBLIC_KEY,
        "usdc_mint": config.USDC_MINT,
        "fitness": {
            "source": provider.name,
            "label": provider.label,
            "can_add": isinstance(provider, fitness.LoggedProvider),
            "types": list(fitness.ACTIVITY_TYPES),
        },
        "pick_themes": [{"id": k, "label": v["label"]} for k, v in pickrounds.THEMES.items()],
        "max_pick_points": pickrounds.MAX_PICK_POINTS,
    }


@app.get("/verifier")
def verifier() -> dict:
    """Public: who signs Proof of Effort records, and the scoring rules they vouch for."""
    return {
        "public_key": config.VERIFIER_PUBLIC_KEY,
        "domain": attest.DOMAIN,
        "schema": attest.SCHEMA,
        "cluster": attest.CLUSTER,
        "program": str(chain.PROGRAM_ID),
        "rules": {"version": scoring.RULES_VERSION, "sha256": scoring.rules_fingerprint()},
        "trust": "A proof shows our verifier approved this result and that the score sheet was not changed "
                 "afterwards. It does not prove a workout happened.",
    }


@app.post("/me/name")
def set_name(body: NewName, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """The name other players see on the leaderboard and in the feed."""
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(400, "Enter a name.")
    user.display_name = name
    session.commit()
    return _user_view(user)


@app.get("/me/challenges")
def my_challenges(
    mode: Literal[MODES] | None = None,  # type: ignore[valid-type]
    user: db.User = Depends(current_user), session: Session = Depends(db.get_session),
) -> list[dict]:
    """Challenges the caller joined, created, or was invited to (optionally one mode only), newest first."""
    joined = {c.id: c for c in scores.challenges_of(session, user.id)}
    found = dict(joined)
    for c in session.scalars(select(db.Challenge).where(db.Challenge.creator_id == user.id)):
        found[c.id] = c
    invited = select(db.Invite.challenge_id).where(db.Invite.user_id == user.id)
    for c in session.scalars(select(db.Challenge).where(db.Challenge.id.in_(invited))):
        found[c.id] = c
    ordered = sorted(found.values(), key=lambda c: c.start_time, reverse=True)
    return [
        {**_challenge_view(c), "joined": c.id in joined, "is_creator": c.creator_id == user.id}
        for c in ordered if mode is None or _mode(c) == mode
    ]


def _player_counts(session: Session, challenges: list[db.Challenge]) -> dict[str, int]:
    """Players per challenge, from the latest PlayerJoined event the Stream delivered."""
    counts: dict[str, int] = {}
    rows = session.scalars(
        select(db.ChainEvent).where(
            db.ChainEvent.name == "PlayerJoined", db.ChainEvent.challenge.in_([c.address for c in challenges])
        )
    )
    for row in rows:
        counts[row.challenge] = max(counts.get(row.challenge, 0), json.loads(row.data)["player_count"])
    return counts


@app.get("/events/public")
def public_events(_user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> list[dict]:
    """Public events that are still open for joining, soonest kick-off first. League and private events never appear."""
    now = datetime.now(timezone.utc)
    open_events = [
        c for c in session.scalars(
            select(db.Challenge)
            .where(db.Challenge.mode == "public", db.Challenge.status == "open")
            .order_by(db.Challenge.start_time)
        )
        if db.utc(c.start_time) > now
    ]
    counts = _player_counts(session, open_events)
    return [
        {**_challenge_view(c), "player_count": counts.get(c.address, 0), "max_players": MAX_PLAYERS,
         "pot": c.buy_in_units * counts.get(c.address, 0) / 10**config.USDC_DECIMALS}
        for c in open_events
    ]


@app.post("/invites/redeem")
def redeem_invite(
    body: InviteCode, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Checks an invite code. A right code lets the caller see and join that event from now on."""
    typed = "".join(body.code.split())
    # New codes are upper case without dashes; older ones are mixed case and may contain "-".
    tidy = typed.replace("-", "").upper()
    challenge = session.scalar(select(db.Challenge).where(db.Challenge.invite_code.in_({typed, tidy})))
    if challenge is None:
        raise HTTPException(404, "That code doesn't match any event. Check it and try again.")
    if _mode(challenge) != "public" and not _can_see(session, challenge, user):
        session.add(db.Invite(challenge_id=challenge.id, user_id=user.id))
        try:
            session.commit()
        except IntegrityError:  # a double click stored it a moment ago
            session.rollback()
    return _challenge_view(challenge)


@app.get("/challenges/{address}/state")
def challenge_state(
    address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Everything the challenge screen shows, in one call. The web app asks for this every few seconds.

    The feed, the pool total, and "deposit confirmed" all come from events the QuickNode Stream delivered.
    The leaderboard is included only for players of the challenge.
    """
    challenge = session.scalar(select(db.Challenge).where(db.Challenge.address == address))
    if challenge is not None and not _can_see(session, challenge, user):
        raise HTTPException(404, "We do not know that challenge.")
    rows = events.challenge_events(session, address)
    wallets = set()
    pool_units = player_count = None
    deposit_confirmed = False
    for row in rows:
        data = json.loads(row.data)
        wallets.update(w for w in [data.get("creator"), data.get("player"), *data.get("winners", [])] if w)
        if row.name == "PlayerJoined":
            pool_units, player_count = data["pool_total"], data["player_count"]
            deposit_confirmed = deposit_confirmed or data["player"] == user.wallet_address
        elif row.name in ("ChallengeSettled", "ChallengeSettledSplit", "ChallengeRefunded"):
            pool_units = 0
    names = {
        u.wallet_address: scores.display_name(u)
        for u in session.scalars(select(db.User).where(db.User.wallet_address.in_(wallets)))
    } if wallets else {}
    is_player = challenge is not None and _is_player(session, challenge, user)
    players = None
    format_state = None
    rounds = None
    has_rounds = challenge is not None and bool(pickrounds.settings(challenge)[1])
    if is_player:
        if has_rounds:
            _update_rounds(session, challenge)
        board = scores.leaderboard(session, challenge)
        fmt = scores.format_view(challenge, board)
        players = [
            {"rank": r["rank"], "name": r["name"], "points": r["points"], "ticks": r["ticks"],
             "base_points": r["base_points"], "pick_points": r["pick_points"],
             "team": r["team"], "projected_share": fmt["projected"].get(r["user_id"], 0),
             "goal_progress": fmt.get("progress", {}).get(r["user_id"]),
             "is_you": r["user_id"] == user.id}
            for r in board
        ]
        format_state = {k: v for k, v in fmt.items() if k not in ("projected", "progress")}
        if has_rounds:
            # Its own name: `names` (wallet -> name) is still needed for the feed below.
            round_names = {r["user_id"]: r["name"] for r in board}
            all_rounds = pickrounds.rounds_of(session, challenge)
            rounds = {
                "total": pickrounds.round_count(challenge),
                "max_points": pickrounds.MAX_PICK_POINTS,
                # Live odds only for the newest round; older ones show the odds when they opened.
                "list": [pickrounds.round_view(session, r, user.id, round_names, live=(r is all_rounds[-1]))
                         for r in all_rounds],
            }
    return {
        "challenge": _challenge_view(challenge) if challenge else None,
        "you": {
            "joined": is_player,
            "deposit_confirmed": deposit_confirmed,
            "is_creator": challenge is not None and challenge.creator_id == user.id,
            "is_admin": _is_admin(user),
        },
        "settle_tx": challenge.settle_tx if challenge else None,
        "pool": None if pool_units is None else pool_units / 10**config.USDC_DECIMALS,
        "player_count": player_count,
        "players": players,
        "format": format_state,  # players only: team table, and whether a goal has been missed so far
        "rounds": rounds,
        # A wallet with no account here (or one that never shared a name) is shown by its last 4 characters.
        "feed": events.feed(rows, lambda wallet: names.get(wallet, f"Player {wallet[-4:]}")),
    }


def _update_rounds(session: Session, challenge: db.Challenge) -> None:
    """Opens the round that is due and reads finished games' results. Never breaks the screen."""
    try:
        pickrounds.open_due_round(session, challenge)
        pickrounds.resolve(session, challenge)
    except Exception:
        session.rollback()
        log.exception("Could not update prediction rounds for %s", challenge.address)


# ---------- Stage 6: settlement and payout ----------


def _finish(session: Session, challenge: db.Challenge, end_now: bool = False) -> dict:
    try:
        return settlement.finish(session, challenge, end_now=end_now)
    except settlement.NotYet as e:
        raise HTTPException(409, str(e)) from e
    except TimeoutError as e:
        log.exception("Settlement not confirmed for %s", challenge.address)
        raise HTTPException(504, "This is taking longer than usual. Check again in a minute.") from e
    except Exception as e:
        log.exception("Could not finish %s", challenge.address)
        raise HTTPException(503, "Could not finish the challenge right now. Try again in a moment.") from e


@app.post("/challenges/{address}/finish")
def finish_challenge(
    address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Does whatever is due: pays the winner once the challenge is over, or refunds if fewer than 2 joined.

    Any player may ask; the server decides what is due and works out the result itself.
    """
    challenge = _visible_challenge(session, address, user)
    if not (_is_player(session, challenge, user) or challenge.creator_id == user.id or _is_admin(user)):
        raise HTTPException(403, "Only players of this challenge can do that.")
    return _finish(session, challenge)


@app.post("/admin/challenges/{address}/end-now")
def end_now(address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """Admin "End week now": ends the challenge onchain, then settles it (or refunds). For demos and testing."""
    if not _is_admin(user):
        raise HTTPException(403, "Only an admin can end a challenge early.")
    return _finish(session, _stored_challenge(session, address), end_now=True)


@app.post("/internal/tick")
def tick(request: Request, session: Session = Depends(db.get_session)) -> dict:
    """The automatic path: a scheduler calls this every few minutes to finish every challenge that is due."""
    if not config.TICK_SECRET:
        raise HTTPException(503, "TICK_SECRET is not set on the server")
    if not secrets.compare_digest(request.headers.get("x-tick-secret", ""), config.TICK_SECRET):
        raise HTTPException(401, "Wrong secret")
    return {"finished": settlement.finish_all_due(session)}


@app.get("/challenges/{address}/score-sheet")
def score_sheet(address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """The final points behind a settlement, with the hash that was stored onchain, so players can check it."""
    challenge = _visible_challenge(session, address, user)
    if not _is_player(session, challenge, user):
        raise HTTPException(403, "Only players of this challenge can see its score sheet.")
    if not challenge.score_sheet:
        raise HTTPException(404, "This challenge has not been settled.")
    sheet = json.loads(challenge.score_sheet)
    payout = settlement.payout_of(sheet)
    proof = json.loads(challenge.attestation) if challenge.attestation else None
    return {
        "sheet": sheet,
        # The exact text that was hashed, so a browser can hash it without re-creating Python's JSON.
        "canonical": attest.canonical(sheet),
        "payout": {"note": payout.note, "shares_bps": dict(payout.shares)},
        "sha256": settlement.sheet_hash(sheet).hex(),
        "transaction": challenge.settle_tx,
        "proof": proof,
        "proof_problems": attest.check(proof, challenge=challenge.address, sheet=sheet) if proof else None,
    }


# ---------- Prediction rounds (Gemini Prediction Markets) ----------


class RoundPickBody(BaseModel):
    option_id: str = Field(min_length=1, max_length=60)


@app.post("/challenges/{address}/rounds/{number}/pick")
def make_round_pick(
    address: str, number: int, body: RoundPickBody,
    user: db.User = Depends(current_user), session: Session = Depends(db.get_session),
) -> dict:
    """Saves the caller's pick in a round, at the market's current probability. Changeable until kick-off."""
    challenge = _visible_challenge(session, address, user)
    if not _is_player(session, challenge, user):
        raise HTTPException(403, "Join this challenge to make a pick.")
    round_ = session.scalar(
        select(db.PickRound).where(db.PickRound.challenge_id == challenge.id, db.PickRound.number == number - 1)
    )
    if round_ is None:
        raise HTTPException(404, "That round hasn't opened.")
    if challenge.status != "open":
        raise HTTPException(409, "This challenge is over.")
    try:
        pickrounds.save_pick(session, round_, user.id, body.option_id)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    except Exception as e:
        log.exception("Could not check the pick with Gemini")
        raise HTTPException(503, "Couldn't save your pick right now. Try again in a moment.") from e
    return pickrounds.round_view(session, round_, user.id, {user.id: scores.display_name(user)})


# ---------- League stats (CSV from the organizer) ----------


class StatsUpload(BaseModel):
    csv: str = Field(min_length=1, max_length=500_000)


class StatsMatch(BaseModel):
    matches: dict[int, str | None]  # user ID -> name on the sheet (None to unlink)


@app.get("/stats/template.csv", response_class=PlainTextResponse)
def stats_template() -> PlainTextResponse:
    return PlainTextResponse(
        leaguestats.TEMPLATE, media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=league_stats_template.csv"},
    )


def _stats_challenge(session: Session, address: str, user: db.User) -> db.Challenge:
    """A league-stats event the caller organizes. Only the organizer uploads and matches stats."""
    challenge = _visible_challenge(session, address, user)
    if challenge.creator_id != user.id:
        raise HTTPException(403, "Only the organizer can manage the stat sheet.")
    if not scores.uses_league_stats(challenge):
        raise HTTPException(409, "This event is scored from workouts, not a stat sheet.")
    return challenge


@app.get("/challenges/{address}/stats")
def stats_summary(address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    challenge = _stats_challenge(session, address, user)
    return leaguestats.summary(session, challenge, scores.display_name)


@app.post("/challenges/{address}/stats")
def upload_stats(
    address: str, body: StatsUpload, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    challenge = _stats_challenge(session, address, user)
    if challenge.status != "open":
        raise HTTPException(409, "This event is over; its stats can't change.")
    try:
        result = leaguestats.upload(session, challenge, body.csv, scores.display_name)
    except leaguestats.BadSheet as e:
        raise HTTPException(400, str(e)) from e
    return {**result, **leaguestats.summary(session, challenge, scores.display_name)}


@app.post("/challenges/{address}/stats/match")
def match_stats(
    address: str, body: StatsMatch, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    challenge = _stats_challenge(session, address, user)
    if challenge.status != "open":
        raise HTTPException(409, "This event is over; its stats can't change.")
    try:
        leaguestats.match(session, challenge, body.matches)
    except leaguestats.BadSheet as e:
        raise HTTPException(400, str(e)) from e
    return leaguestats.summary(session, challenge, scores.display_name)


@app.delete("/me/fitness")
def disconnect_fitness(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """Disconnect: deletes the caller's fitness data and their points in unsettled challenges. They stay in the pool."""
    scores.forget_user(session, user.id)
    return {"disconnected": True}


# ---------- Oura connection (OAuth only) ----------


class OuraStart(BaseModel):
    return_to: str = Field(max_length=500)  # the web app page to come back to; must be one of WEB_ORIGIN


class OuraComplete(BaseModel):
    state: str = Field(min_length=20, max_length=200)


def _oura(action):
    """Runs an Oura step, turning its errors into plain HTTP errors (messages never hold tokens)."""
    try:
        return action()
    except oura.OuraError as e:
        raise HTTPException(e.status, str(e)) from None
    except secretbox.NotConfigured:
        log.error("Oura: TOKEN_ENCRYPTION_KEY is missing or wrong")
        raise HTTPException(503, "Connecting Oura isn't available on this server yet.") from None


@app.get("/integrations/oura")
def oura_status(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    return oura.status(session, user.id)


@app.post("/integrations/oura/start")
def oura_start(body: OuraStart, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    return {"url": _oura(lambda: oura.start(session, user.id, body.return_to))}


@app.get("/integrations/oura/callback", include_in_schema=False)
def oura_callback(
    state: str | None = None, code: str | None = None, error: str | None = None,
    session: Session = Depends(db.get_session),
) -> RedirectResponse:
    """Oura's redirect. No Rival login here, so nothing is connected yet: the web app finishes it."""
    try:
        target = oura.callback(session, state, code, error)
    except secretbox.NotConfigured:
        log.error("Oura: TOKEN_ENCRYPTION_KEY is missing or wrong")
        target = oura.back_to(oura.fallback_return(), oura="error", reason="unavailable")
    response = RedirectResponse(target, status_code=303)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.post("/integrations/oura/complete")
def oura_complete(body: OuraComplete, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    _oura(lambda: oura.complete(session, user.id, body.state))
    return oura.status(session, user.id)


@app.delete("/integrations/oura")
def oura_disconnect(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    revoked = _oura(lambda: oura.disconnect(session, user.id))
    return {**oura.status(session, user.id), "revoked": revoked}


@app.get("/integrations/oura/workouts")
def oura_workouts(
    days: int = Query(30, ge=1, le=90), limit: int = Query(10, ge=1, le=25),
    user: db.User = Depends(current_user), session: Session = Depends(db.get_session),
) -> JSONResponse:
    """Read-only test: the caller's own recent Oura workouts and heart-rate coverage. Nothing is stored or logged."""
    report = _oura(lambda: oura_data.recent_workouts(session, user.id, days=days, limit=limit))
    return JSONResponse(report, headers={"Cache-Control": "no-store, private"})
