"""Settlement: winners, ties, refunds, the score-sheet hash, and who may trigger what. No network needed."""

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone

import pytest
from solders.pubkey import Pubkey
from solders.signature import Signature
from sqlalchemy import select

import attest
import chain
import config
import formats
import db
import events
import settlement
from test_stage4 import CHALLENGE, WALLETS, board, challenge, client, fakes, make_token, state  # noqa: F401


_READ: dict[str, chain.Rules] = {}  # what the pretend chain read, so a payout needs no second database session


def stored_rules(address) -> chain.Rules | None:
    """The onchain Rules account, as create_challenge would have written it for the stored ruleset.
    (Read once per challenge: opening a session mid-payout would roll back the test's shared connection.)"""
    if str(address) in _READ:
        return _READ[str(address)]
    with db.SessionLocal() as session:
        row = session.scalar(select(db.Challenge).where(db.Challenge.address == str(address)))
        text = row.ruleset if row else None
    if text is None:
        return None
    ruleset = json.loads(text)
    _READ[str(address)] = found = chain.Rules(Pubkey.from_string(str(address)), Pubkey.from_string(str(address)),
                       hashlib.sha256(text.encode()).digest(), Pubkey.from_string(ruleset["verifier"]),
                       ruleset["payout"]["kind"], ruleset["payout"]["split_bps"])
    return found


def program_checks(address, winners, verifier, message, signature):
    """What the program checks before any payout: the Ed25519 signature by the verifier in the rules
    account, over a v2 message for this program, challenge and rules hash, naming these winners."""
    rules = stored_rules(address)
    assert rules is not None, "no Rules account"
    assert verifier == rules.verifier, "WrongVerifier"
    assert Signature.from_bytes(signature).verify(verifier, message), "Ed25519 check failed"
    fields = attest.parse_v2(message)
    assert fields["program"] == str(chain.PROGRAM_ID) and fields["challenge"] == str(address)
    assert fields["rules_hash"] == rules.rules_hash.hex(), "InvalidSignedResult"
    assert [p["wallet"] for p in fields["payout"]] == [str(w) for w in winners]
    return rules, fields


@pytest.fixture(autouse=True)
def fake_chain(monkeypatch, fakes):
    """A pretend Solana: records what the oracle sent and changes the pretend challenge like the program would."""
    sent = []
    fakes.vault = fakes.mint
    _READ.clear()

    def end_early(client, oracle, address):
        fakes.end_time = int(time.time()) - 1
        fakes.start_time = min(fakes.start_time, fakes.end_time)
        sent.append(("end_early",))
        return "end-sig"

    def settle(client, oracle, address, winners, verifier, message, signature):
        assert time.time() >= fakes.end_time and len(fakes.players) >= 2
        rules, fields = program_checks(address, winners, verifier, message, signature)
        assert rules.payout != "podium", "WrongPayoutKind"
        assert [p["bps"] for p in fields["payout"]] == [b for _, b in formats._equal([str(w) for w in winners])]
        fakes.status = "settled"
        sent.append(("settle", [str(w) for w in winners], bytes.fromhex(fields["score_sheet_sha256"])))
        return "settle-sig"

    def refund(client, payer, address):
        fakes.status = "refunded"
        sent.append(("refund",))
        return "refund-sig"

    monkeypatch.setattr(chain, "fetch_challenge", lambda client, address: fakes)
    monkeypatch.setattr(chain, "fetch_rules", lambda client, address: stored_rules(address))
    monkeypatch.setattr(chain, "load_oracle", lambda: object())
    monkeypatch.setattr(chain, "end_early", end_early)
    monkeypatch.setattr(chain, "settle", settle)
    monkeypatch.setattr(chain, "refund", refund)
    monkeypatch.setattr(events, "catch_up", lambda session, address: 0)
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"maya@example.com"})
    monkeypatch.setattr(config, "SETTLE_GRACE_SECONDS", 0)
    monkeypatch.setattr(config, "TICK_SECRET", "")  # whatever the developer's own .env says
    return sent


def workout(client, who, **body):
    started = (datetime.now(timezone.utc) - timedelta(minutes=40)).isoformat()
    reply = client.post("/me/activities", json={"type": "run", "minutes": 30, "start": started, **body},
                        headers=make_token(who))
    assert reply.status_code == 200


def test_admin_ends_now_and_the_top_scorer_wins(client, challenge, fake_chain):
    workout(client, "sam", distance_km=5)
    workout(client, "maya")
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 200
    body = reply.json()
    assert body["action"] == "settled" and body["winners"] == [WALLETS["sam"]] and body["end_signature"] == "end-sig"
    assert [call[0] for call in fake_chain] == ["end_early", "settle"]
    assert state(client)["challenge"]["status"] == "settled" and state(client)["settle_tx"] == "settle-sig"


def test_the_hash_sent_onchain_matches_the_published_score_sheet(client, challenge, fake_chain):
    workout(client, "sam", distance_km=5)
    client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    published = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("sam")).json()
    sheet = published["sheet"]
    assert sheet["scores"] == [{"wallet": WALLETS["maya"], "points": 0}, {"wallet": WALLETS["sam"], "points": 2}]
    assert len(sheet["salt"]) == 32 and set(sheet) == {"challenge", "rules", "rules_version", "rules_sha256", "rules_hash", "format", "scores", "salt"}  # no fitness details
    assert sheet["format"] == {"name": "winner_takes_all"}
    recomputed = hashlib.sha256(json.dumps(sheet, sort_keys=True, separators=(",", ":")).encode()).digest()
    assert fake_chain[-1][2] == recomputed and published["sha256"] == recomputed.hex()
    assert client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("zoe")).status_code == 403


def test_a_tie_pays_both_players(client, challenge, fake_chain):
    workout(client, "sam")
    workout(client, "maya")
    body = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya")).json()
    assert body["winners"] == [WALLETS["maya"], WALLETS["sam"]]


def test_nobody_scoring_splits_the_pool_between_everyone(client, challenge):
    body = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya")).json()
    assert sorted(body["winners"]) == sorted([WALLETS["maya"], WALLETS["sam"]])


def test_a_player_who_never_shared_points_scores_zero(client, fakes, fake_chain):
    client.post("/challenges", json={"address": CHALLENGE, "name": "Office week"}, headers=make_token("maya"))
    client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True}, headers=make_token("maya"))
    workout(client, "maya")  # Sam deposited onchain but never recorded his join with us
    body = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya")).json()
    assert body["winners"] == [WALLETS["maya"]]


def test_only_admins_can_end_early(client, challenge, fake_chain):
    assert client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("sam")).status_code == 403
    assert fake_chain == []


def test_finish_waits_for_the_end_then_settles(client, challenge, fakes, fake_chain):
    url = f"/challenges/{CHALLENGE}/finish"
    assert client.post(url, headers=make_token("sam")).status_code == 409  # still running
    assert client.post(url, headers=make_token("zoe")).status_code == 403  # not a player
    fakes.end_time = int(time.time()) - 5
    assert client.post(url, headers=make_token("sam")).json()["action"] == "settled"
    assert [call[0] for call in fake_chain] == ["settle"]
    again = client.post(url, headers=make_token("sam")).json()  # already done: nothing is sent twice
    assert again["action"] == "none" and len(fake_chain) == 1


def test_grace_period_delays_settlement(client, challenge, fakes, fake_chain, monkeypatch):
    monkeypatch.setattr(config, "SETTLE_GRACE_SECONDS", 3600)
    fakes.end_time = int(time.time()) - 5
    assert client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("sam")).status_code == 409
    assert fake_chain == []


def test_too_few_players_get_a_refund(client, challenge, fakes, fake_chain):
    fakes.players = [WALLETS["maya"]]
    body = client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya")).json()
    assert body["action"] == "refunded" and [call[0] for call in fake_chain] == ["refund"]
    assert state(client)["challenge"]["status"] == "refunded"


def test_no_refund_while_joining_is_open(client, challenge, fakes, fake_chain):
    fakes.players = [WALLETS["maya"]]
    fakes.start_time = int(time.time()) + 600
    assert client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya")).status_code == 409
    assert fake_chain == []


def test_only_activities_before_the_early_end_count(client, challenge, fake_chain):
    workout(client, "sam", distance_km=5)
    client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    with db.SessionLocal() as session:
        stored = session.scalar(select(db.Challenge))
        assert db.utc(stored.end_time) <= datetime.now(timezone.utc)
    assert board(client)["sam"]["points"] == 2  # the result is frozen once settled


def test_tick_needs_the_secret_and_finishes_what_is_due(client, challenge, fakes, fake_chain, monkeypatch):
    assert client.post("/internal/tick").status_code == 503  # no secret configured
    monkeypatch.setattr(config, "TICK_SECRET", "s3cret")
    assert client.post("/internal/tick", headers={"X-Tick-Secret": "nope"}).status_code == 401
    assert client.post("/internal/tick", headers={"X-Tick-Secret": "s3cret"}).json() == {"finished": []}
    fakes.end_time = int(time.time()) - 5
    done = client.post("/internal/tick", headers={"X-Tick-Secret": "s3cret"}).json()["finished"]
    assert [d["action"] for d in done] == ["settled"] and done[0]["address"] == CHALLENGE


def test_a_failed_transaction_leaves_the_challenge_open(client, challenge, fakes, monkeypatch):
    def boom(*args):
        raise RuntimeError("rpc down")
    monkeypatch.setattr(chain, "settle", boom)
    fakes.end_time = int(time.time()) - 5
    assert client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("sam")).status_code == 503
    assert state(client)["challenge"]["status"] == "open" and settlement._busy == set()


def test_new_columns_are_added_to_an_existing_table():
    from sqlalchemy import create_engine, inspect, text
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE challenges (id INTEGER PRIMARY KEY, address VARCHAR)"))
    old = db.engine
    db.engine = engine
    try:
        db.init_db()
    finally:
        db.engine = old
    assert {"settle_tx", "score_sheet"} <= {c["name"] for c in inspect(engine).get_columns("challenges")}


def test_database_address_forgives_copy_paste_slips():
    import pytest

    import config

    want = "postgresql+psycopg://u:p@host.example/db?sslmode=require"
    plain = "postgresql://u:p@host.example/db?sslmode=require"
    for pasted in (plain, f"  {plain}\n", f'"{plain}"', f"'{plain}'", f"DATABASE_URL={plain}",
                   f'DATABASE_URL="{plain}"', f"psql '{plain}'", plain.replace("postgresql://", "postgres://")):
        assert config.clean_database_url(pasted) == want
    assert config.clean_database_url("sqlite://") == "sqlite://"
    for bad in ("", "host.example/db", "postgresql://u:secret@host /db"):
        with pytest.raises(RuntimeError) as error:
            config.clean_database_url(bad)
        assert "secret" not in str(error.value)


def test_web_origin_is_cut_down_to_scheme_and_host():
    import config

    for pasted in ("https://someone.github.io", "https://someone.github.io/", " 'https://someone.github.io/my-repo/' "):
        assert config.clean_origin(pasted) == "https://someone.github.io"
    assert config.clean_origin("http://localhost:5173") == "http://localhost:5173"
