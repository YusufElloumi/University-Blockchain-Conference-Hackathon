"""Loser Buys API. Run from api/:  uvicorn main:app --reload

Stage 2 endpoints (all need the Privy login token in "Authorization: Bearer <token>"):
    POST /me/setup   save the user, and quietly send their wallet fee money if it is low
    POST /me/fund    "Add test funds": send devnet USDC once per user

Stage 3 endpoints:
    POST /webhooks/quicknode            onchain events delivered by the QuickNode Stream (signature checked)
    GET  /challenges/{address}/events   the stored events for one challenge (public onchain data)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import json

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.orm import Session

import config
import auth
import db
import events
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


def _user_view(user: db.User, usdc_units: int | None = None) -> dict:
    return {
        "wallet": user.wallet_address,
        "email": user.email,
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
