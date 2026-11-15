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
"""

from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Literal

import json

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from solana.rpc.api import Client
from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import config
import auth
import chain
import db
import events
import fitness
import scores
import settlement
import treasury

log = logging.getLogger("loser_buys")


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
        raise HTTPException(409, "Test funds were already added to this account.")
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
        raise HTTPException(503, "Could not add test funds right now. Try again in a moment.") from e
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


class NewChallenge(BaseModel):
    address: str
    name: str = Field(min_length=1, max_length=60)


class JoinRecord(BaseModel):
    consent: bool  # "Share my challenge points with this group"
    deposit_tx: str | None = Field(default=None, max_length=100)


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


def _challenge_view(challenge: db.Challenge) -> dict:
    return {
        "address": challenge.address,
        "name": challenge.name,
        "template": challenge.template,
        "buy_in": challenge.buy_in_units / 10**config.USDC_DECIMALS,
        "start": db.utc(challenge.start_time).isoformat(),
        "end": db.utc(challenge.end_time).isoformat(),
        "status": challenge.status,
        "invite_code": challenge.invite_code,
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
    state = onchain_challenge(body.address)
    if str(state.creator) != user.wallet_address:
        raise HTTPException(403, "Only the person who created this challenge can set it up.")
    return _challenge_view(_register(session, body.address, state, body.name.strip(), user.id))


def _register(session: Session, address: str, state: chain.Challenge, name: str, creator_id: int | None) -> db.Challenge:
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
        invite_code=secrets.token_urlsafe(6),
        creator_id=creator_id,
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
        state = onchain_challenge(address)
        challenge = _register(session, address, state, "Weekly challenge", None)
    if not _is_player(session, challenge, user):
        state = state or onchain_challenge(address)
        if user.wallet_address not in {str(p) for p in state.players}:
            raise HTTPException(409, "We have not seen your deposit yet. Try again in a moment.")
        session.add(
            db.Participant(
                challenge_id=challenge.id, user_id=user.id, deposit_tx=body.deposit_tx,
                consent_at=datetime.now(timezone.utc),
            )
        )
        try:
            session.commit()
        except IntegrityError:  # a double click stored it a moment ago
            session.rollback()
        scores.recompute(session, challenge, user.id)
    return {"challenge": _challenge_view(challenge), "joined": True}


@app.get("/challenges/{address}/leaderboard")
def challenge_leaderboard(
    address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Points and daily ticks only. Players agreed to share these with their group, so only the group sees them."""
    challenge = _stored_challenge(session, address)
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
def my_activities(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> list[dict]:
    """The caller's own activities from the last 30 days, newest first. Only ever their own."""
    provider = _provider()
    now = datetime.now(timezone.utc)
    activities = provider.fetch_activities(session, user.id, now - timedelta(days=30), now + timedelta(days=1))
    return [_activity_view(a, provider) for a in reversed(activities)]


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
def my_challenges(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> list[dict]:
    """Challenges the caller joined or created, newest first."""
    found = {c.id: c for c in scores.challenges_of(session, user.id)}
    for c in session.scalars(select(db.Challenge).where(db.Challenge.creator_id == user.id)):
        found[c.id] = c
    ordered = sorted(found.values(), key=lambda c: c.start_time, reverse=True)
    return [_challenge_view(c) for c in ordered]


@app.get("/challenges/{address}/state")
def challenge_state(
    address: str, user: db.User = Depends(current_user), session: Session = Depends(db.get_session)
) -> dict:
    """Everything the challenge screen shows, in one call. The web app asks for this every few seconds.

    The feed, the pool total, and "deposit confirmed" all come from events the QuickNode Stream delivered.
    The leaderboard is included only for players of the challenge.
    """
    challenge = session.scalar(select(db.Challenge).where(db.Challenge.address == address))
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
        elif row.name in ("ChallengeSettled", "ChallengeRefunded"):
            pool_units = 0
    names = {
        u.wallet_address: scores.display_name(u)
        for u in session.scalars(select(db.User).where(db.User.wallet_address.in_(wallets)))
    } if wallets else {}
    is_player = challenge is not None and _is_player(session, challenge, user)
    players = None
    if is_player:
        players = [
            {"rank": r["rank"], "name": r["name"], "points": r["points"], "ticks": r["ticks"],
             "is_you": r["user_id"] == user.id}
            for r in scores.leaderboard(session, challenge)
        ]
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
        "feed": events.feed(rows, lambda wallet: names.get(wallet, "A player")),
    }


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
    challenge = _stored_challenge(session, address)
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
    challenge = _stored_challenge(session, address)
    if not _is_player(session, challenge, user):
        raise HTTPException(403, "Only players of this challenge can see its score sheet.")
    if not challenge.score_sheet:
        raise HTTPException(404, "This challenge has not been settled.")
    sheet = json.loads(challenge.score_sheet)
    return {"sheet": sheet, "sha256": settlement.sheet_hash(sheet).hex(), "transaction": challenge.settle_tx}


@app.delete("/me/fitness")
def disconnect_fitness(user: db.User = Depends(current_user), session: Session = Depends(db.get_session)) -> dict:
    """Disconnect: deletes the caller's fitness data and their points in unsettled challenges. They stay in the pool."""
    scores.forget_user(session, user.id)
    return {"disconnected": True}
