"""Proof of Effort (issue #1): signed results, the checks on them, and per-workout states. No network needed."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from solders.keypair import Keypair

import attest
import chain
import config
import scoring
import settlement
from test_stage4 import CHALLENGE, WALLETS, challenge, client, fakes, make_token  # noqa: F401
from test_stage6 import fake_chain, workout  # noqa: F401

VERIFIER = Keypair()
OTHER_CHALLENGE = "Bm4GyR7JqH8aXVNz3pR2tK5vW9cE1fLs6dQ2uYhT7oPx"


@pytest.fixture(autouse=True)
def verifier(monkeypatch):
    monkeypatch.setattr(attest, "load_verifier", lambda: VERIFIER)
    monkeypatch.setattr(config, "VERIFIER_PUBLIC_KEY", str(VERIFIER.pubkey()))


def settled(client):
    """Sam wins a challenge; returns the published score sheet with its proof."""
    workout(client, "sam", distance_km=5)
    assert client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya")).status_code == 200
    return client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("sam")).json()


def resign(payload: dict, keypair: Keypair = VERIFIER) -> dict:
    return attest.sign(payload, keypair)


def test_settling_issues_a_proof_that_checks_out(client, challenge, fake_chain):
    published = settled(client)
    proof, sheet = published["proof"], published["sheet"]
    assert published["proof_problems"] == []
    payload = json.loads(proof["message"])
    assert payload["challenge"] == CHALLENGE and payload["cluster"] == "devnet" and payload["domain"] == attest.DOMAIN
    assert payload["program"] == str(chain.PROGRAM_ID)
    assert payload["payout"] == [{"wallet": WALLETS["sam"], "bps": 10_000}]
    assert payload["rules"] == {"name": "daily_mover", "version": scoring.RULES_VERSION, "sha256": scoring.rules_fingerprint()}
    # The hash in the proof is the one the program received.
    sent_hash = next(call[2] for call in fake_chain if call[0] == "settle")
    assert payload["score_sheet_sha256"] == sent_hash.hex() == published["sha256"]
    assert attest.check(proof, challenge=CHALLENGE, sheet=sheet, onchain_hash=sent_hash) == []
    # The browser hashes this text as-is.
    assert published["canonical"] == attest.canonical(sheet)


def test_a_proof_holds_no_fitness_data(client, challenge, fake_chain):
    payload = json.loads(settled(client)["proof"]["message"])
    assert set(payload) == {"schema", "domain", "cluster", "program", "challenge", "rules", "score_sheet_sha256",
                            "payout", "issued_at", "nonce", "verifier"}
    text = json.dumps(payload).lower()
    for word in ("run", "km", "minutes", "distance", "device", "points"):
        assert f'"{word}' not in text


def test_an_edited_message_fails_the_signature(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    payload = json.loads(proof["message"])
    payload["payout"] = [{"wallet": WALLETS["maya"], "bps": 10_000}]
    forged = {**proof, "message": attest.canonical(payload)}
    assert "the signature does not match the message" in attest.check(forged, challenge=CHALLENGE)


def test_a_changed_score_sheet_is_caught(client, challenge, fake_chain):
    published = settled(client)
    sheet = published["sheet"]
    sheet["scores"][0]["points"] = 99  # give Maya the win after the fact
    problems = attest.check(published["proof"], challenge=CHALLENGE, sheet=sheet)
    assert "the score sheet does not match the signed hash" in problems
    assert "the signed payout is not what the score sheet gives" in problems


def test_a_proof_cannot_be_replayed_on_another_challenge(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    assert "challenge is" in attest.check(proof, challenge=OTHER_CHALLENGE)[0]


@pytest.mark.parametrize("field,value", [("cluster", "mainnet-beta"), ("program", str(Keypair().pubkey())),
                                         ("domain", "someone-else"), ("schema", 2)])
def test_a_proof_for_another_network_program_or_purpose_fails(client, challenge, fake_chain, field, value):
    payload = json.loads(settled(client)["proof"]["message"])
    payload[field] = value
    problems = attest.check(resign(payload), challenge=CHALLENGE)
    assert any(p.startswith(field) for p in problems)


def test_a_proof_signed_by_anyone_else_fails(client, challenge, fake_chain):
    payload = json.loads(settled(client)["proof"]["message"])
    impostor = Keypair()
    payload["verifier"] = str(impostor.pubkey())
    problems = attest.check(resign(payload, impostor), challenge=CHALLENGE)
    assert problems == [f"signed by {impostor.pubkey()}, not by the published verifier {VERIFIER.pubkey()}"]


def test_a_hash_that_differs_from_the_chain_fails(client, challenge, fake_chain):
    proof = settled(client)["proof"]
    assert attest.check(proof, challenge=CHALLENGE, onchain_hash=bytes(32)) == ["the signed hash is not the one stored onchain"]


def test_garbage_is_not_a_proof():
    assert attest.check({"message": "{}", "signature": "zz"}, challenge=CHALLENGE)[0].startswith("not a readable proof")


def test_without_a_verifier_key_settlement_still_pays(client, challenge, fake_chain, monkeypatch):
    monkeypatch.setattr(attest, "load_verifier", lambda: None)
    published = settled(client)
    assert published["proof"] is None and published["transaction"] == "settle-sig"


def test_the_verifier_is_published(client):
    body = client.get("/verifier").json()
    assert body["public_key"] == str(VERIFIER.pubkey())
    assert body["rules"] == {"version": scoring.RULES_VERSION, "sha256": scoring.rules_fingerprint()}


def test_rules_fingerprint_changes_with_the_rules(monkeypatch):
    before = scoring.rules_fingerprint()
    monkeypatch.setattr(scoring, "KM_PER_POINT", 4)
    assert scoring.rules_fingerprint() != before


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
