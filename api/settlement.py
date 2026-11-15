"""Ends a challenge: works out the final scores and has the program pay the winner(s), or refund.

The server holds the oracle key, the only key the program accepts results from. What limits that
trust: winners must be players (checked by the program), the hash of the final score sheet is
stored onchain so published scores cannot be changed later, and every settlement is a public
transaction.

No fitness data goes onchain: only winner addresses and the salted hash.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import threading
import time
from datetime import datetime, timezone

from solana.rpc.api import Client
from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.orm import Session

import chain
import config
import db
import events
import pickem
import scores

log = logging.getLogger("loser_buys")
_busy: set[str] = set()  # challenges being finished right now, so two requests cannot both pay out
_busy_lock = threading.Lock()


class NotYet(Exception):
    """Nothing can be done for this challenge yet (the message is safe to show)."""


def sheet_hash(sheet: dict) -> bytes:
    """SHA-256 of the score sheet written as compact JSON with sorted keys. This is what goes onchain."""
    return hashlib.sha256(json.dumps(sheet, sort_keys=True, separators=(",", ":")).encode()).digest()


def build_sheet(session: Session, challenge: db.Challenge, players: list[str]) -> dict:
    """Final points for every onchain player, after pulling each player's activities one last time."""
    participants = session.scalars(select(db.Participant.user_id).where(db.Participant.challenge_id == challenge.id))
    for user_id in participants:
        scores.recompute(session, challenge, user_id)
    points = {row["wallet"]: row["points"] for row in scores.leaderboard(session, challenge)}
    return {
        "challenge": challenge.address,
        "rules": challenge.template,
        # A player who deposited but never agreed to share points has no score with us: zero.
        "scores": [{"wallet": wallet, "points": points.get(wallet, 0)} for wallet in players],
        "salt": secrets.token_hex(16),  # stops anyone guessing the sheet from the hash alone
    }


def winners_of(sheet: dict) -> list[str]:
    """Everyone tied on the top score. They split the pool equally."""
    best = max(entry["points"] for entry in sheet["scores"])
    return [entry["wallet"] for entry in sheet["scores"] if entry["points"] == best]


def _sync_times(challenge: db.Challenge, state: chain.Challenge) -> None:
    challenge.start_time = datetime.fromtimestamp(state.start_time, timezone.utc)
    challenge.end_time = datetime.fromtimestamp(state.end_time, timezone.utc)


def finish(session: Session, challenge: db.Challenge, end_now: bool = False) -> dict:
    """Does whatever is due for a challenge: refund it, settle it, or raise NotYet.

    `end_now` is the admin's "End week now": it first ends the challenge onchain (a visible event).
    """
    with _busy_lock:
        if challenge.address in _busy:
            raise NotYet("This challenge is being finished right now.")
        _busy.add(challenge.address)
    try:
        return _finish(session, challenge, end_now)
    finally:
        with _busy_lock:
            _busy.discard(challenge.address)


def _finish(session: Session, challenge: db.Challenge, end_now: bool) -> dict:
    client = Client(chain.RPC_URL)
    address = Pubkey.from_string(challenge.address)
    state = chain.fetch_challenge(client, address)
    if state.status != "open":
        challenge.status = state.status
        session.commit()
        return {"action": "none", "status": state.status, "signature": challenge.settle_tx}

    oracle = chain.load_oracle()
    result: dict = {}
    if end_now and time.time() < state.end_time:
        result["end_signature"] = chain.end_early(client, oracle, address)
        state = chain.fetch_challenge(client, address)
    _sync_times(challenge, state)
    session.commit()
    now = time.time()

    if len(state.players) < 2:
        if now < state.start_time:
            raise NotYet("Joining is still open.")
        signature = chain.refund(client, oracle, address)
        challenge.status, challenge.settle_tx = "refunded", signature
        result.update(action="refunded", status="refunded", signature=signature)
    else:
        grace = 0 if end_now else config.SETTLE_GRACE_SECONDS
        if now < state.end_time + grace:
            raise NotYet("The challenge has not finished yet.")
        sheet = build_sheet(session, challenge, [str(p) for p in state.players])
        # A tie is broken by the pick'em: a tied player whose pick was right wins outright.
        winners, tiebreak = pickem.break_tie(session, challenge, winners_of(sheet))
        if tiebreak:
            sheet["tiebreak"] = tiebreak
        signature = chain.settle(client, oracle, address, [Pubkey.from_string(w) for w in winners], sheet_hash(sheet))
        challenge.status, challenge.settle_tx, challenge.score_sheet = "settled", signature, json.dumps(sheet)
        result.update(action="settled", status="settled", signature=signature, winners=winners)
    session.commit()
    try:
        events.catch_up(session, challenge.address)  # in case the Stream is not delivering right now
    except Exception:
        log.exception("Could not catch up on events after finishing %s", challenge.address)
    return result


def finish_all_due(session: Session) -> list[dict]:
    """The automatic path: finishes every open challenge that is due. Called by a scheduler."""
    done = []
    for challenge in session.scalars(select(db.Challenge).where(db.Challenge.status == "open")).all():
        if db.utc(challenge.start_time) > datetime.now(timezone.utc):
            continue
        try:
            done.append({"address": challenge.address, **finish(session, challenge)})
        except NotYet:
            continue
        except Exception as e:
            log.exception("Could not finish %s", challenge.address)
            done.append({"address": challenge.address, "action": "error", "error": str(e)[:200]})
    return done
