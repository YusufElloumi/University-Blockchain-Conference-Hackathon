"""Locked rules: the ruleset, its hash, and the check that the chain holds exactly those rules. No network."""

import hashlib
import json

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

import chain
import rules
import scoring
from test_stage4 import CHALLENGE, VERIFIER, WALLETS, client, fakes, make_token  # noqa: F401

PODIUM = {"mode": "private", "format": "podium", "format_config": {"shares": [60, 30, 10]}}


def preview(client, **settings):
    reply = client.post("/rules", json={"length_seconds": 7 * 86400, **settings})
    assert reply.status_code == 200, reply.text
    return reply.json()


def lock(fakes, preview_reply, **changes):
    """Puts a Rules account onchain as create_challenge would, from a POST /rules reply."""
    values = dict(
        rules_hash=bytes.fromhex(preview_reply["rules_hash"]), verifier=Pubkey.from_string(preview_reply["verifier"]),
        payout=preview_reply["payout"]["kind"], split_bps=preview_reply["payout"]["split_bps"],
    )
    values.update(changes)
    key = Pubkey.from_string(CHALLENGE)
    fakes.rules = chain.Rules(address=key, challenge=key, **values)


def record(client, **settings):
    return client.post("/challenges", json={"address": CHALLENGE, "name": "Locked", **settings},
                       headers=make_token("maya"))


def test_the_preview_gives_the_canonical_text_its_hash_and_the_payout_terms(client, fakes):
    body = preview(client, **PODIUM)
    assert hashlib.sha256(body["ruleset"].encode()).hexdigest() == body["rules_hash"]
    assert body["payout"] == {"kind": "podium", "split_bps": [6000, 3000, 1000], "kind_index": 1}
    assert body["verifier"] == str(VERIFIER.pubkey())
    ruleset = json.loads(body["ruleset"])
    assert rules.canonical(ruleset) == body["ruleset"]  # canonical: re-encoding gives the same text
    assert ruleset["scoring"] == {"source": "fitness", "version": scoring.RULES_VERSION,
                                  "sha256": scoring.rules_fingerprint(), "stat_weights": None}
    assert ruleset["workouts"] == {"count": ["verified", "flagged"], "never_count": ["rejected"]}
    assert ruleset["consent_required"] is True and ruleset["length_seconds"] == 7 * 86400
    assert ruleset["max_players"] == 8 and ruleset["mode"] == "private" and ruleset["program"] == str(chain.PROGRAM_ID)


def test_the_ruleset_holds_no_personal_or_fitness_data(client, fakes):
    text = preview(client, **PODIUM)["ruleset"].lower()
    for word in ("@", "email", "maya", "km\"", "distance", "minutes\""):
        assert word not in text


def test_every_setting_changes_the_hash(client, fakes):
    base = preview(client, **PODIUM)["rules_hash"]
    variants = [
        {**PODIUM, "format_config": {"shares": [70, 20, 10]}},
        {**PODIUM, "mode": "public"},
        {**PODIUM, "pick_themes": ["basketball"], "round_hours": 24},
        {"mode": "private", "format": "winner_takes_all"},
    ]
    hashes = {preview(client, **v)["rules_hash"] for v in variants}
    assert base not in hashes and len(hashes) == len(variants)
    assert client.post("/rules", json={"length_seconds": 3600, **PODIUM}).json()["rules_hash"] != base


def test_bad_settings_are_refused_before_anything_goes_onchain(client):
    reply = client.post("/rules", json={"length_seconds": 3600, "format": "podium", "format_config": {"shares": [50, 60]}})
    assert reply.status_code == 400


def test_a_challenge_is_recorded_only_with_exactly_the_locked_rules(client, fakes):
    body = preview(client, **PODIUM)
    lock(fakes, body)
    reply = record(client, **PODIUM)
    assert reply.status_code == 200, reply.text
    view = reply.json()
    assert view["rules_hash"] == body["rules_hash"] and view["ruleset"] == body["ruleset"]
    assert view["payout_terms"]["label"] == "60 / 30 / 10"


@pytest.mark.parametrize("changes, words", [
    ({"rules_hash": bytes(32)}, "not the rules you chose"),
    ({"split_bps": [5000, 3000, 2000]}, "payout locked onchain"),
    ({"payout": "winner_takes_all", "split_bps": []}, "payout locked onchain"),
    ({"verifier": Keypair().pubkey()}, "different verifier"),
])
def test_anything_else_onchain_is_refused(client, fakes, changes, words):
    lock(fakes, preview(client, **PODIUM), **changes)
    reply = record(client, **PODIUM)
    assert reply.status_code == 400 and words in reply.json()["detail"]


def test_settings_that_differ_from_the_locked_ones_are_refused(client, fakes):
    lock(fakes, preview(client, **PODIUM))
    reply = record(client, **{**PODIUM, "format_config": {"shares": [50, 30, 20]}})
    assert reply.status_code == 400


def test_a_challenge_with_no_rules_account_is_refused(client, fakes):
    fakes.rules = None
    assert record(client, **PODIUM).status_code == 400


def test_the_length_and_player_cap_come_from_the_chain(client, fakes):
    body = preview(client, length_seconds=fakes.end_time - fakes.start_time, max_players=8, **PODIUM)
    lock(fakes, body)
    fakes.max_players = 4  # the chain says 4, the preview said 8: different rules
    assert record(client, **PODIUM).status_code == 400
    fakes.max_players = 8
    assert record(client, **PODIUM).status_code == 200


def test_a_script_made_challenge_with_the_default_rules_is_recorded_on_first_join(client, fakes):
    lock(fakes, preview(client, mode="public", length_seconds=fakes.end_time - fakes.start_time))
    reply = client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True}, headers=make_token("sam"))
    assert reply.status_code == 200, reply.text
    state = client.get(f"/challenges/{CHALLENGE}/state", headers=make_token("sam")).json()
    assert state["challenge"]["rules_hash"] is not None and state["challenge"]["mode"] == "public"


def test_a_script_made_challenge_with_other_rules_is_refused(client, fakes):
    lock(fakes, preview(client, mode="public", length_seconds=3600 * 5))  # valid, but not this challenge's length
    reply = client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True}, headers=make_token("sam"))
    assert reply.status_code == 400


def test_payout_labels():
    assert rules.describe_payout({"kind": "podium", "split_bps": [6000, 3000, 1000]}) == "60 / 30 / 10"
    assert rules.describe_payout({"kind": "winner_takes_all", "split_bps": []}) == "winner takes all"
    assert WALLETS  # (imported for the shared fixtures)
