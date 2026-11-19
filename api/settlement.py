"""Ends a challenge: works out the final scores and has the program pay the winner(s), or refund.

The server holds the oracle key, the only key the program accepts results from. What limits that
trust: winners must be players (checked by the program), the hash of the final score sheet is
stored onchain so published scores cannot be changed later, and every settlement is a public
transaction.

No fitness data goes onchain: only winner addresses and the salted hash.

Locked rules (`rules.py`): each challenge commits to a ruleset before anyone pays; its hash and the
payout terms sit in the challenge's onchain Rules account. Settlement scores with the committed rules
version or refuses; it never re-scores under rules nobody agreed to.

Proof of Effort (`attest.py`, v2): the verifier key signs the result as a fixed binary message, and
the settle transaction carries Solana's Ed25519 check of that signature right before `settle` /
`settle_split`. The program pays only the winners and shares in the signed message, for this
challenge's rules hash, and (podium) only the shares its locked split gives. The proof is kept with
the challenge and shown to its players. Challenges created before rules were locked can only be
refunded (72 hours after the end, or at once if fewer than 2 joined).
"""

from __future__ import annotations

import base64
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

import attest
import chain
import config
import db
import events
import formats
import leaguestats
import pickrounds
import rules
import scores
import scoring

log = logging.getLogger("loser_buys")
_busy: set[str] = set()  # challenges being finished right now, so two requests cannot both pay out
_busy_lock = threading.Lock()


REFUND_TIMEOUT_SECONDS = 72 * 3600  # the program's REFUND_TIMEOUT_SECONDS


class NotYet(Exception):
    """Nothing can be done for this challenge yet (the message is safe to show)."""


def sheet_hash(sheet: dict) -> bytes:
    """SHA-256 of the score sheet written as compact JSON with sorted keys. This is what goes onchain."""
    return attest.sheet_sha256(sheet)


def build_sheet(session: Session, challenge: db.Challenge, players: list[str]) -> dict:
    """Final points for every onchain player, after pulling each player's activities one last time."""
    participants = session.scalars(select(db.Participant.user_id).where(db.Participant.challenge_id == challenge.id))
    for user_id in participants:
        scores.recompute(session, challenge, user_id)
    rows = {row["wallet"]: row for row in scores.leaderboard(session, challenge)}
    fmt, settings = formats.of(challenge)

    def entry(wallet: str) -> dict:
        row = rows.get(wallet)  # a player who deposited but never agreed to share points has no score with us: zero
        found = {"wallet": wallet, "points": row["points"] if row else 0}
        if fmt == "goal":
            found["active_days"] = row["active_days"] if row else 0
        if fmt == "teams":
            found["team"] = row["team"] if row else None
        return found

    sheet = {
        "challenge": challenge.address,
        "rules": challenge.template,
        "rules_version": scoring.RULES_VERSION,  # the exact scoring numbers used, by name and by hash
        "rules_sha256": scoring.rules_fingerprint(),
        "rules_hash": None,  # the onchain rules hash of the locked ruleset; filled in by _finish
        "format": {"name": fmt, **settings},  # fixed at creation; part of the hash
        "scores": [entry(wallet) for wallet in players],
        "salt": secrets.token_hex(16),  # stops anyone guessing the sheet from the hash alone
    }
    if scores.uses_league_stats(challenge):
        sheet["rules"] = "league_stats"
        sheet["rules_version"], sheet["rules_sha256"] = leaguestats.RULES_VERSION, None  # weights are hashed below
        sheet["league_stats"] = {"weights": leaguestats.weights(challenge),
                                 "sha256": leaguestats.stats_hash(session, challenge)}
    rounds = pickrounds.rounds_of(session, challenge)
    if rounds:
        sheet["prediction_rounds"] = {
            "source": "Gemini Prediction Markets",
            "max_points": pickrounds.MAX_PICK_POINTS,
            "rounds": [{"market": r.event_ticker, "status": r.status, "winner": r.winning_option_id} for r in rounds],
        }
    return sheet


def payout_of(sheet: dict) -> formats.Payout:
    """Who is paid and how much, by the format written in the sheet. Ties are handled by each format's rules."""
    settings = dict(sheet.get("format") or {"name": formats.DEFAULT_FORMAT})
    fmt = settings.pop("name")
    found = [formats.Entry(e["wallet"], e["points"], e.get("active_days", 0), e.get("team")) for e in sheet["scores"]]
    return formats.payout(fmt, settings, found)


def winners_of(sheet: dict) -> list[str]:
    """Everyone the pool is paid to."""
    return payout_of(sheet).wallets


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
        # Prediction rounds: wait for Gemini's results, up to RESULT_WAIT after the end. Then (or at once,
        # for an admin's early end) any round still without a result is void and scores nothing.
        locked = chain.fetch_rules(client, address)
        ruleset = rules.of(challenge)
        if locked is None or ruleset is None:
            # Created before rules were locked onchain: the program cannot pay it out, only refund it.
            if now < state.end_time + REFUND_TIMEOUT_SECONDS:
                raise NotYet("This challenge was created before rules were locked onchain, so it can't be paid "
                             "out. Every entry fee will be refunded 72 hours after it ends.")
            signature = chain.refund(client, oracle, address)
            challenge.status, challenge.settle_tx = "refunded", signature
            result.update(action="refunded", status="refunded", signature=signature)
            session.commit()
            return result
        try:
            rules.check_current(ruleset)  # never re-score under rules nobody agreed to
        except rules.RulesError as e:
            raise NotYet(str(e)) from e
        verifier = attest.load_verifier()
        if verifier is None or verifier.pubkey() != locked.verifier:
            raise NotYet("The verifier key named in this challenge's rules is not available, so the result "
                         "can't be signed. Payout waits until it is.")
        waited = now - state.end_time >= pickrounds.RESULT_WAIT.total_seconds()
        if not pickrounds.resolve(session, challenge, give_up=end_now or waited):
            raise NotYet("Waiting for game results from Gemini.")
        sheet = build_sheet(session, challenge, [str(p) for p in state.players])
        sheet["rules_hash"] = locked.rules_hash.hex()
        payout = payout_of(sheet)  # follows from the sheet alone, so anyone holding it can check the payout
        keys = [Pubkey.from_string(w) for w in payout.wallets]
        proof = attest.issue_v2(challenge.address, locked.rules_hash, sheet, payout.shares, verifier)
        message, signed = base64.b64decode(proof["message"]), bytes.fromhex(proof["signature"])
        if payout.groups is None:
            signature = chain.settle(client, oracle, address, keys, verifier.pubkey(), message, signed)
        else:
            signature = chain.settle_split(client, oracle, address, keys, payout.groups, verifier.pubkey(),
                                           message, signed)
        proof["settle_tx"] = signature
        challenge.status, challenge.settle_tx, challenge.score_sheet = "settled", signature, json.dumps(sheet)
        challenge.attestation = json.dumps(proof)
        result.update(action="settled", status="settled", signature=signature, winners=payout.wallets,
                      note=payout.note)
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
        try:  # prediction rounds move on even when nobody has the challenge screen open
            pickrounds.open_due_round(session, challenge)
            pickrounds.resolve(session, challenge)
        except Exception:
            session.rollback()
            log.exception("Could not update prediction rounds for %s", challenge.address)
        try:
            done.append({"address": challenge.address, **finish(session, challenge)})
        except NotYet:
            continue
        except Exception as e:
            log.exception("Could not finish %s", challenge.address)
            done.append({"address": challenge.address, "action": "error", "error": str(e)[:200]})
    return done
