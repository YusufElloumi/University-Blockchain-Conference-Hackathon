"""Proof of Sweat ("Proof of Effort" in code): signed results the program checks at payout, the offchain
checks on them, locked rules, and per-workout states. No network needed."""

import base64
import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

import attest
import chain
import config
import formats
import scoring
import settlement
from test_stage4 import CHALLENGE, VERIFIER, WALLETS, challenge, client, fakes, make_token  # noqa: F401
from test_stage6 import fake_chain, workout  # noqa: F401

OTHER_CHALLENGE = "Bm4GyR7JqH8aXVNz3pR2tK5vW9cE1fLs6dQ2uYhT7oPx"
FIXTURE = json.loads((Path(__file__).parent.parent.parent / "onchain" / "shared" / "proof_v2_fixture.json").read_text())


def settled(client):
    """Sam wins a challenge; returns the published score sheet with its proof."""
    workout(client, "sam", distance_km=5)
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    return client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("sam")).json()


def edited(proof: dict, at: int, value: int) -> dict:
    """The proof with one byte of its signed message changed (and the signature left alone)."""
    message = bytearray(base64.b64decode(proof["message"]))
    message[at] = value
    return {**proof, "message": base64.b64encode(bytes(message)).decode()}


# ---------- the shared v2 message fixture (same bytes in Python, TypeScript and the program) ----------


def test_python_builds_the_shared_fixture_byte_for_byte():
    message = attest.message_v2(
        Pubkey.from_string(FIXTURE["program"]), Pubkey.from_string(FIXTURE["challenge"]),
        bytes.fromhex(FIXTURE["rules_hash"]), bytes.fromhex(FIXTURE["score_hash"]),
        [Pubkey.from_string(w) for w in FIXTURE["winners"]], FIXTURE["shares_bps"],
    )
    assert message.hex() == FIXTURE["message_hex"] and len(message) == FIXTURE["message_length"]
    parsed = attest.parse_v2(message)
    assert parsed["payout"] == [{"wallet": w, "bps": b} for w, b in zip(FIXTURE["winners"], FIXTURE["shares_bps"])]
    assert parsed["rules_hash"] == FIXTURE["rules_hash"] and parsed["score_sheet_sha256"] == FIXTURE["score_hash"]


def test_the_program_id_in_the_fixture_is_ours():
    assert FIXTURE["program"] == str(chain.PROGRAM_ID)


@pytest.mark.parametrize("bad", [b"", attest.DOMAIN_V2, bytes.fromhex(FIXTURE["message_hex"])[:-1],
                                 b"rival.proof-of-effort.v1" + bytes.fromhex(FIXTURE["message_hex"])[24:]])
def test_malformed_messages_are_refused(bad):
    with pytest.raises(ValueError):
        attest.parse_v2(bad)


# ---------- v2 proofs from settlement ----------


def test_settling_issues_a_v2_proof_the_program_checked(client, challenge, fake_chain):
    published = settled(client)
    proof, sheet = published["proof"], published["sheet"]
    assert published["proof_problems"] == []
    assert proof["schema"] == 2 and proof["domain"] == "rival.proof-of-effort.v2" and proof["cluster"] == "devnet"
    assert proof["program"] == str(chain.PROGRAM_ID) and proof["challenge"] == CHALLENGE
    assert proof["payout"] == [{"wallet": WALLETS["sam"], "bps": 10_000}]
    assert proof["settle_tx"] == "settle-sig" and proof["verifier"] == str(VERIFIER.pubkey())
    # Its rules hash is the hash of the published ruleset, which is also in the score sheet.
    assert proof["rules_hash"] == hashlib.sha256(published["ruleset"].encode()).hexdigest() == sheet["rules_hash"]
    # The score hash in the proof is the one the program stored.
    stored = next(call[2] for call in fake_chain if call[0] == "settle")
    assert proof["score_sheet_sha256"] == stored.hex() == published["sha256"]
    assert attest.check_v2(proof, challenge=CHALLENGE, sheet=sheet, onchain_hash=stored,
                           onchain_rules_hash=bytes.fromhex(proof["rules_hash"]), ruleset_text=published["ruleset"]) == []
    assert published["canonical"] == attest.canonical(sheet)  # the browser hashes this text as-is


def test_a_proof_holds_no_fitness_data(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    assert set(proof) == {"schema", "domain", "cluster", "program", "challenge", "rules_hash", "score_sheet_sha256",
                          "payout", "message", "signature", "verifier", "issued_at", "settle_tx", "checked_onchain"}
    assert len(base64.b64decode(proof["message"])) == 24 + 32 * 4 + 1 + 34  # one winner: keys, hashes, share
    text = json.dumps(proof).lower()
    for word in ("run", "km", "minutes", "distance", "device", "points"):
        assert f'"{word}' not in text


def test_an_edited_message_fails_the_signature(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    forged = edited(proof, len(base64.b64decode(proof["message"])) - 1, 0)  # change the share
    problems = attest.check_v2(forged, challenge=CHALLENGE)
    assert "the signature does not match the message" in problems
    assert "the readable payout does not match the signed message" in problems


def test_a_changed_score_sheet_is_caught(client, challenge, fake_chain):
    published = settled(client)
    sheet = published["sheet"]
    sheet["scores"][0]["points"] = 99  # give Maya the win after the fact
    problems = attest.check_v2(published["proof"], challenge=CHALLENGE, sheet=sheet)
    assert "the score sheet does not match the signed hash" in problems
    assert "the signed payout is not what the score sheet gives" in problems


def test_a_proof_cannot_be_replayed_on_another_challenge(client, challenge, fake_chain):
    assert "it is for another challenge" in attest.check_v2(settled(client)["proof"], challenge=OTHER_CHALLENGE)


def test_a_proof_signed_by_anyone_else_fails(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    impostor = Keypair()
    message = base64.b64decode(proof["message"])
    forged = {**proof, "verifier": str(impostor.pubkey()), "signature": bytes(impostor.sign_message(message)).hex()}
    assert attest.check_v2(forged, challenge=CHALLENGE) == [
        f"signed by {impostor.pubkey()}, not by the published verifier {VERIFIER.pubkey()}"]


def test_hashes_that_differ_from_the_chain_or_the_published_rules_fail(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    assert attest.check_v2(proof, challenge=CHALLENGE, onchain_hash=bytes(32)) == [
        "the signed score hash is not the one stored onchain"]
    assert attest.check_v2(proof, challenge=CHALLENGE, onchain_rules_hash=bytes(32)) == [
        "the signed rules hash is not the one locked onchain"]
    assert attest.check_v2(proof, challenge=CHALLENGE, ruleset_text='{"edited":true}') == [
        "the published rules do not hash to the signed rules hash"]


def test_garbage_is_not_a_proof():
    assert attest.check_v2({"message": "!!", "signature": "zz"}, challenge=CHALLENGE)[0].startswith("not a readable proof")


def test_without_the_verifier_key_nothing_is_paid(client, challenge, fake_chain, monkeypatch):
    """The program refuses a payout without the verifier's signature, so the server does not even try."""
    monkeypatch.setattr(attest, "load_verifier", lambda: None)
    workout(client, "sam", distance_km=5)
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 409 and "verifier key" in reply.json()["detail"]
    assert [call[0] for call in fake_chain] == ["end_early"]


def test_a_different_verifier_than_the_locked_one_pays_nothing(client, challenge, fake_chain, monkeypatch):
    monkeypatch.setattr(attest, "load_verifier", lambda: Keypair())
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 409 and not any(call[0] == "settle" for call in fake_chain)


def test_the_verifier_is_published(client):
    body = client.get("/verifier").json()
    assert body["public_key"] == str(VERIFIER.pubkey()) and body["domain"] == "rival.proof-of-effort.v2"
    assert body["rules"] == {"version": scoring.RULES_VERSION, "sha256": scoring.rules_fingerprint()}


def test_rules_fingerprint_changes_with_the_rules(monkeypatch):
    before = scoring.rules_fingerprint()
    monkeypatch.setattr(scoring, "KM_PER_POINT", 4)
    assert scoring.rules_fingerprint() != before


# ---------- committed rules versions ----------


def test_a_challenge_is_never_rescored_under_newer_rules(client, challenge, fake_chain, monkeypatch):
    """The rules version is locked at creation. If the server's rules change, settlement stops instead."""
    workout(client, "sam", distance_km=5)
    monkeypatch.setattr(scoring, "RULES_VERSION", "daily-mover-v2")
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 409
    assert "locked scoring rules daily-mover-v1" in reply.json()["detail"] and "will not be re-scored" in reply.json()["detail"]
    assert not any(call[0] == "settle" for call in fake_chain)
    monkeypatch.setattr(scoring, "RULES_VERSION", "daily-mover-v1")  # back on the committed rules: it settles
    assert client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya")).status_code == 200
    assert fake_chain[-1][0] == "settle"


def test_a_changed_scoring_number_is_also_caught(client, challenge, fake_chain, monkeypatch):
    monkeypatch.setattr(scoring, "KM_PER_POINT", 4)  # same version name, different numbers
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 409 and "will not be re-scored" in reply.json()["detail"]


# ---------- challenges created before rules were locked ----------


def test_a_challenge_without_locked_rules_is_refund_only(client, challenge, fake_chain, fakes):
    import db
    with db.SessionLocal() as session:
        session.query(db.Challenge).update({db.Challenge.ruleset: None})
        session.commit()
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 409 and "refunded 72 hours after it ends" in reply.json()["detail"]
    fakes.end_time = int(time.time()) - settlement.REFUND_TIMEOUT_SECONDS - 1
    body = client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya")).json()
    assert body["action"] == "refunded" and fake_chain[-1] == ("refund",)


# ---------- v1 proofs (before locked rules) still verify ----------


def test_old_v1_proofs_still_check_out_and_say_they_were_not_checked_onchain():
    sheet = {"challenge": CHALLENGE, "rules": "daily_mover", "rules_version": scoring.RULES_VERSION,
             "rules_sha256": scoring.rules_fingerprint(), "format": {"name": "winner_takes_all"},
             "scores": [{"wallet": WALLETS["sam"], "points": 2}, {"wallet": WALLETS["maya"], "points": 0}], "salt": "00"}
    payout = formats.payout("winner_takes_all", {}, [formats.Entry(WALLETS["sam"], 2), formats.Entry(WALLETS["maya"], 0)])
    proof = attest.issue(CHALLENGE, sheet, payout, VERIFIER)
    assert attest.check(proof, challenge=CHALLENGE, sheet=sheet, onchain_hash=attest.sheet_sha256(sheet)) == []
    assert attest.check_any(proof, challenge=CHALLENGE, sheet=sheet, onchain_rules_hash=bytes(32)) == []
    forged = {**proof, "message": proof["message"].replace(WALLETS["sam"], WALLETS["maya"])}
    assert "the signature does not match the message" in attest.check(forged, challenge=CHALLENGE)


# ---------- Workout states, shown only to their owner ----------


def states(client, who="sam"):
    reply = client.get(f"/me/activities?challenge={CHALLENGE}", headers=make_token(who))
    assert reply.status_code == 200
    return [(a["status"], a["reason"]) for a in reply.json()]


def test_a_device_recorded_workout_is_verified(client, challenge):
    workout(client, "sam")
    assert states(client) == [("verified", None)]


def test_an_impossible_workout_is_rejected_with_a_reason(client, challenge):
    workout(client, "sam", minutes=10, distance_km=30)
    assert states(client) == [("rejected", "impossibly fast")]


def test_an_overlapping_copy_is_rejected(client, challenge):
    started = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    for _ in range(2):
        client.post("/me/activities", json={"type": "run", "minutes": 30, "start": started}, headers=make_token("sam"))
    assert sorted(states(client)) == [("rejected", "overlaps another activity"), ("verified", None)]


def test_a_hand_typed_workout_is_flagged(client, challenge, monkeypatch):
    monkeypatch.setattr(config, "FITNESS_PROVIDER", "manual")
    workout(client, "sam")
    status, reason = states(client)[0]
    assert status == "flagged" and "by hand" in reason


def test_states_are_only_given_for_your_own_challenges(client, challenge):
    reply = client.get(f"/me/activities?challenge={OTHER_CHALLENGE}", headers=make_token("sam"))
    assert reply.status_code == 404


def test_the_score_sheet_names_its_rules(client, challenge, fake_chain):
    sheet = settled(client)["sheet"]
    assert sheet["rules_version"] == scoring.RULES_VERSION and sheet["rules_sha256"] == scoring.rules_fingerprint()
    assert settlement.sheet_hash(sheet) == attest.sheet_sha256(sheet)
