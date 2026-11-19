"""Ends a challenge: works out the final scores and has the program pay the winner(s), or refund.

The server holds the oracle key, the only key the program accepts results from. What limits that
trust: winners must be players (checked by the program), the hash of the final score sheet is
stored onchain so published scores cannot be changed later, and every settlement is a public
transaction.

No fitness data goes onchain: only winner addresses and the salted hash.

Proof of Effort (`attest.py`): before paying out, the verifier key signs the result. The proof is
kept with the challenge and shown to its players, so anyone of them can check it independently.
"""

from __future__ import annotations

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
import scores
import scoring
import sweat
from fitness import oura_sync

log = logging.getLogger("loser_buys")
_busy: set[str] = set()  # challenges being finished right now, so two requests cannot both pay out
_busy_lock = threading.Lock()


class NotYet(Exception):
    """Nothing can be done for this challenge yet (the message is safe to show)."""


def sheet_hash(sheet: dict) -> bytes:
    """SHA-256 of the score sheet written as compact JSON with sorted keys. This is what goes onchain."""
    return attest.sheet_sha256(sheet)


RECEIPT_DOMAIN = "rival.proof-of-sweat.receipt"
RECEIPT_SCHEMA = 1


def receipt_commitment(payload: dict) -> str:
    """SHA-256 (hex) of a receipt in canonical form. The receipt carries a random salt, so the
    commitment reveals nothing about the workout and cannot be guessed from the few possible values."""
    return attest.sheet_sha256(payload).hex()


def sweat_section(session: Session, challenge: db.Challenge, players: list[str], sync: dict[int, str] | None,
                  store: bool) -> dict:
    """The Proof of Sweat part of a score sheet: per player, verified minutes, points, and one salted
    commitment per assessed workout. No workout times, provider IDs or heart-rate data.

    With `store`, each receipt's full text is saved for its owner (sweat_receipts); not committed here.
    """
    users = {u.wallet_address: u for u in session.scalars(
        select(db.User).join(db.Participant, db.Participant.user_id == db.User.id)
        .where(db.Participant.challenge_id == challenge.id))}
    fingerprint = sweat.rules_fingerprint()
    listed = []
    for wallet in players:
        user = users.get(wallet)
        entry = {"wallet": wallet, "eligible_minutes": 0, "fitness_points": 0, "receipts": [],
                 "sync": (sync or {}).get(user.id, "not_recorded") if user else "not_a_rival_player"}
        if user is not None:
            sheet = scores.sweat_sheet(session, challenge, user.id)
            entry["eligible_minutes"], entry["fitness_points"] = sheet.eligible_minutes, sheet.total
            for row in scores.imported_rows(session, challenge, user.id):
                line = sheet.lines.get(oura_sync.as_workout(row).ref)
                if line is None:
                    continue
                payload = receipt_payload(challenge.address, wallet, fingerprint, row, line)
                commitment = receipt_commitment(payload)
                entry["receipts"].append(commitment)
                if store:
                    session.add(db.SweatReceipt(challenge_id=challenge.id, user_id=user.id, commitment=commitment,
                                                payload=attest.canonical(payload)))
            entry["receipts"].sort()
        listed.append(entry)
    return {"schema": RECEIPT_SCHEMA, "receipt_domain": RECEIPT_DOMAIN, "provider": oura_sync.PROVIDER,
            "participants": listed}


def receipt_payload(challenge: str, wallet: str, fingerprint: str, row: db.ImportedActivity, line: sweat.Line,
                    salt: str | None = None) -> dict:
    """One workout's result in one challenge, bound to that challenge, wallet, program and rule set."""
    checks = [{"code": c.code, "result": c.result, "reason": c.reason} for c in oura_sync.checks_of(row)]
    checks += [
        {"code": "window", "result": line.window, "reason": line.reason if line.window == sweat.FAILED else None},
        {"code": "duplicate", "result": line.overlap, "reason": line.reason if line.overlap != sweat.PASSED else None},
        {"code": "scoring", "result": sweat.PASSED if line.status == sweat.VERIFIED else line.status
         if line.status == sweat.PENDING else sweat.FAILED, "reason": None},
    ]
    return {
        "schema": RECEIPT_SCHEMA,
        "domain": RECEIPT_DOMAIN,
        "cluster": attest.CLUSTER,
        "program": str(chain.PROGRAM_ID),
        "challenge": challenge,
        "wallet": wallet,
        "rules_version": sweat.RULES_VERSION,
        "rules_sha256": fingerprint,
        "activity": row.activity_type,
        "duration_minutes": int(row.minutes or 0),
        "eligible_minutes": line.eligible_minutes,
        "points": line.points,
        "days": {str(day): seconds // 60 for day, seconds in sorted(line.days.items())},
        "result": line.status,
        "assurance": row.assurance if line.status == sweat.VERIFIED else None,
        "reason": line.reason or row.reason,
        "checks": checks,
        "salt": salt or secrets.token_hex(16),
    }


def build_sheet(session: Session, challenge: db.Challenge, players: list[str], sync: dict[int, str] | None = None,
                commit: bool = True) -> dict:
    """Final points for every onchain player, worked out one last time from what is stored.

    Proof of Sweat challenges read imported workouts only: no call to Oura happens here.
    """
    participants = session.scalars(select(db.Participant.user_id).where(db.Participant.challenge_id == challenge.id))
    for user_id in list(participants):
        scores.recompute(session, challenge, user_id, commit=commit)
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
        "format": {"name": fmt, **settings},  # fixed at creation; part of the hash
        "scores": [entry(wallet) for wallet in players],
        "salt": secrets.token_hex(16),  # stops anyone guessing the sheet from the hash alone
    }
    if scores.is_sweat(challenge):
        sheet["rules_version"], sheet["rules_sha256"] = sweat.RULES_VERSION, sweat.rules_fingerprint()
        sheet["proof_of_sweat"] = sweat_section(session, challenge, players, sync, store=not commit)
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
        is_sweat = scores.is_sweat(challenge)
        # Proof of Sweat: rings sync to Oura's cloud with a delay, so wait a while before fixing the scores.
        grace = 0 if end_now else max(config.SETTLE_GRACE_SECONDS, config.SYNC_GRACE_SECONDS if is_sweat else 0)
        if now < state.end_time:
            raise NotYet("The challenge has not finished yet.")
        if now < state.end_time + grace:
            raise NotYet("Waiting for final workout syncs before the scores are fixed." if is_sweat
                         else "The challenge has not finished yet.")
        # Prediction rounds: wait for Gemini's results, up to RESULT_WAIT after the end. Then (or at once,
        # for an admin's early end) any round still without a result is void and scores nothing.
        waited = now - state.end_time >= pickrounds.RESULT_WAIT.total_seconds()
        if not pickrounds.resolve(session, challenge, give_up=end_now or waited):
            raise NotYet("Waiting for game results from Gemini.")
        sync_states = None
        if is_sweat:
            # Outside the settlement itself: bring every player's imported workouts up to date, by the same
            # rule for all. Bounded: a few tries per player, and no waiting past SYNC_GIVE_UP_SECONDS.
            gave_up = end_now or now - state.end_time >= config.SYNC_GIVE_UP_SECONDS
            ready, sync_states = oura_sync.reconcile_challenge(
                session, challenge, datetime.fromtimestamp(state.end_time, timezone.utc), force=gave_up)
            if not ready:
                raise NotYet("Waiting for final workout syncs before the scores are fixed.")
        # From here to the commit the challenge row is locked (Postgres), and nothing is committed in
        # between, so the points that are hashed and sent onchain are exactly the points that are stored.
        session.execute(select(db.Challenge.id).where(db.Challenge.id == challenge.id).with_for_update())
        sheet = build_sheet(session, challenge, [str(p) for p in state.players], sync=sync_states, commit=False)
        payout = payout_of(sheet)  # follows from the sheet alone, so anyone holding it can check the payout
        keys = [Pubkey.from_string(w) for w in payout.wallets]
        verifier = attest.load_verifier()
        proof = attest.issue(challenge.address, sheet, payout, verifier) if verifier else None
        if proof is None:
            log.warning("VERIFIER_KEYPAIR is not set: settling %s without a Proof of Effort", challenge.address)
        if payout.equal:
            signature = chain.settle(client, oracle, address, keys, sheet_hash(sheet))
        else:
            signature = chain.settle_split(client, oracle, address, keys, [bps for _, bps in payout.shares],
                                           sheet_hash(sheet))
        challenge.status, challenge.settle_tx, challenge.score_sheet = "settled", signature, json.dumps(sheet)
        challenge.attestation = json.dumps(proof) if proof else None
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
    try:  # retention: drop imported workouts no recent challenge needs
        oura_sync.cleanup(session)
    except Exception:
        session.rollback()
        log.exception("Could not clean up imported workouts")
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
