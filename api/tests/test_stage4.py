"""Daily Mover scoring, anti-cheat rules, fitness providers, and the Stage 4 endpoints. No network needed."""

import base64
import json
import struct
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

import auth
import chain
import config
import db
import events
import fitness
import main
import scores
import scoring
from fitness.base import Activity
from fitness.mock import SAMPLE_WEEK, MockProvider

PRIVY_KEY = ec.generate_private_key(ec.SECP256R1())
CHALLENGE = "GNLFdSczFf1GgYXwF1nPLwzTL4Jz5QJrknAMS67vDDc"
WALLETS = {
    "maya": "6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD",
    "sam": "J73KdqANTzJ7P1TMTnd37xNCdXvc3LChG7J8X1XX4XY9",
    "zoe": "AYvBmTfVifruj1XMCGu5pJShLWqo9wYEa1gJFd6pT9re",
}
START = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def act(id, day=0, hour=1, minutes=30, km=0.0, type="run", manual=False, device="Watch"):
    return Activity(id, type, START + timedelta(days=day, hours=hour), minutes, km, device, manual)


def points(activities, **rules):
    return scoring.score_daily_mover(activities, START, END, **rules)


# ---------- scoring rules ----------


def test_twenty_active_minutes_earn_the_daily_point():
    assert points([act("a", minutes=19)]).total == 0
    sheet = points([act("a", minutes=20)])
    assert sheet.total == 1 and sheet.days[0].active


def test_minutes_add_up_within_a_day():
    assert points([act("a", hour=1, minutes=10), act("b", hour=5, minutes=10)]).total == 1


def test_one_point_per_five_km():
    assert points([act("a", minutes=30, km=4.9)]).total == 1
    assert points([act("a", minutes=30, km=5.0)]).total == 2
    assert points([act("a", minutes=15, km=5.0, type="ride")]).total == 1  # distance without the tick


def test_daily_cap_is_three_points():
    sheet = points([act("a", minutes=120, km=42, type="ride")])
    assert sheet.total == 3


def test_days_are_scored_separately():
    sheet = points([act("a", day=0, km=5), act("b", day=1), act("c", day=6, hour=23, km=11)])
    assert {d: s.points for d, s in sheet.days.items()} == {0: 2, 1: 1, 6: 3}
    assert sheet.total == 6


def test_sample_week_scores_as_expected():
    acts = [act(str(i), day=d, hour=h, minutes=m, km=km, type=t) for i, (d, h, t, m, km) in enumerate(SAMPLE_WEEK)]
    sheet = points(acts)
    assert {d: s.points for d, s in sheet.days.items()} == {0: 2, 1: 1, 2: 3, 4: 2, 5: 2, 6: 0}
    assert sheet.rejected == {}


# ---------- anti-cheat ----------


def test_activities_outside_the_window_are_ignored():
    before = Activity("early", "run", START - timedelta(minutes=1), 30, 5, "Watch", False)
    at_end = Activity("late", "run", END, 30, 5, "Watch", False)
    sheet = points([before, at_end, act("ok")])
    assert sheet.total == 1
    assert sheet.rejected == {"early": "outside the challenge dates", "late": "outside the challenge dates"}


def test_manual_entries_are_ignored_when_the_source_does_not_allow_them():
    manual = act("m", manual=True, device=None)
    assert points([manual], counts_manual=False).rejected == {"m": "typed in by hand"}
    assert points([manual], counts_manual=True).total == 1


def test_a_recording_device_can_be_required():
    assert points([act("a", device=None)], requires_device=True).rejected == {"a": "no recording device"}


def test_the_same_activity_twice_counts_once():
    sheet = points([act("a", km=5), act("a", km=5)])
    assert sheet.total == 2 and sheet.days[0].activity_ids == ["a"]


def test_overlapping_activities_are_rejected():
    # Same workout uploaded under two IDs, and one that starts before the first has finished.
    sheet = points([act("a", hour=1, minutes=60), act("b", hour=1, minutes=60), act("c", hour=1.5), act("d", hour=3)])
    assert sheet.rejected == {"b": "overlaps another activity", "c": "overlaps another activity"}
    assert sheet.days[0].activity_ids == ["a", "d"]


def test_impossible_speeds_are_rejected():
    assert points([act("a", minutes=30, km=20, type="run")]).rejected == {"a": "impossibly fast"}  # 40 km/h run
    assert points([act("a", minutes=30, km=20, type="ride")]).total == 3  # 40 km/h ride is fine
    assert points([act("a", minutes=30, km=6, type="walk")]).rejected == {"a": "impossibly fast"}


def test_nonsense_activities_are_rejected():
    sheet = points([act("zero", minutes=0), act("long", day=1, minutes=25 * 60), act("neg", day=3, km=-1)])
    assert sheet.total == 0 and len(sheet.rejected) == 3


# ---------- providers and endpoints ----------


def make_token(who="maya"):
    claims = {"sub": f"did:privy:{who}", "iss": "privy.io", "aud": "test-app-id",
              "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return {"Authorization": "Bearer " + jwt.encode(claims, PRIVY_KEY, algorithm="ES256")}


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """An empty in-memory database, fake Privy, the mock source, and a fake onchain challenge."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db.SessionLocal, "kw", {**db.SessionLocal.kw, "bind": engine})
    monkeypatch.setattr(auth, "_signing_keys", lambda: [PRIVY_KEY.public_key()])
    monkeypatch.setattr(
        auth, "fetch_privy_user",
        lambda pid: auth.PrivyUser(pid, pid.split(":")[-1] + "@example.com", WALLETS[pid.split(":")[-1]]),
    )
    monkeypatch.setattr(config, "FITNESS_PROVIDER", "mock")
    now = datetime.now(timezone.utc)
    onchain = SimpleNamespace(
        creator=WALLETS["maya"], buy_in=1_000_000, status="open", players=[WALLETS["maya"], WALLETS["sam"]],
        oracle=config.ORACLE_PUBLIC_KEY, mint=config.USDC_MINT,
        start_time=int((now - timedelta(days=2)).timestamp()), end_time=int((now + timedelta(days=5)).timestamp()),
    )
    monkeypatch.setattr(main, "onchain_challenge", lambda address: onchain)
    return onchain


@pytest.fixture
def client():
    return TestClient(main.app)


@pytest.fixture
def challenge(client):
    """A recorded challenge that Maya and Sam have joined."""
    assert client.post("/challenges", json={"address": CHALLENGE, "name": "Office week", "mode": "public"},
                       headers=make_token("maya")).status_code == 200
    for who in ("maya", "sam"):
        assert client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True},
                           headers=make_token(who)).status_code == 200
    return CHALLENGE


def board(client, who="maya"):
    reply = client.get(f"/challenges/{CHALLENGE}/leaderboard", headers=make_token(who))
    assert reply.status_code == 200
    return {p["name"]: p for p in reply.json()["players"]}


def test_all_tables_exist():
    assert set(db.Base.metadata.tables) == {
        "users", "fitness_connections", "challenges", "participants", "score_entries", "chain_events",
        "logged_activities", "invites", "pick_rounds", "round_picks", "league_stats", "oauth_states",
    }


def test_provider_is_chosen_by_setting(monkeypatch):
    assert fitness.get_provider().name == "mock"
    monkeypatch.setattr(config, "FITNESS_PROVIDER", "manual")
    assert fitness.get_provider().name == "manual"
    for name in ("strava", "fitbit"):
        monkeypatch.setattr(config, "FITNESS_PROVIDER", name)
        with pytest.raises(fitness.NotSupported):
            fitness.get_provider()


def test_recording_a_challenge_reads_details_from_the_chain(client):
    reply = client.post("/challenges", json={"address": CHALLENGE, "name": "Office week"}, headers=make_token("maya"))
    assert reply.status_code == 200
    body = reply.json()
    assert body["buy_in"] == 1 and body["status"] == "open" and body["invite_code"]
    again = client.post("/challenges", json={"address": CHALLENGE, "name": "Other"}, headers=make_token("maya"))
    assert again.json()["invite_code"] == body["invite_code"] and again.json()["name"] == "Office week"


def test_only_the_creator_can_record_a_challenge(client):
    reply = client.post("/challenges", json={"address": CHALLENGE, "name": "Mine now"}, headers=make_token("sam"))
    assert reply.status_code == 403


def test_joining_needs_consent_and_an_onchain_deposit(client):
    client.post("/challenges", json={"address": CHALLENGE, "name": "Office week", "mode": "public"}, headers=make_token("maya"))
    url = f"/challenges/{CHALLENGE}/join"
    assert client.post(url, json={"consent": False}, headers=make_token("sam")).status_code == 400
    assert client.post(url, json={"consent": True}, headers=make_token("zoe")).status_code == 409  # no deposit
    assert client.post(url, json={"consent": True}, headers=make_token("sam")).status_code == 200
    assert client.post(url, json={"consent": True}, headers=make_token("sam")).status_code == 200  # safe to repeat
    with db.SessionLocal() as session:
        rows = session.scalars(select(db.Participant)).all()
        assert len(rows) == 1 and rows[0].consent_at is not None


def test_adding_an_activity_changes_points(client, challenge):
    assert board(client)["maya"]["points"] == 0
    reply = client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 5.2},
                        headers=make_token("maya"))
    assert reply.status_code == 200
    body = reply.json()
    assert body["activity"]["verified"] is True and body["activity"]["device"] == "Mock Watch"
    assert body["challenges"] == [
        {"address": CHALLENGE, "name": "Office week", "points": 2, "counted": True, "reason": None}
    ]
    players = board(client)
    assert players["maya"]["points"] == 2 and players["maya"]["rank"] == 1 and players["maya"]["is_you"]
    assert players["sam"]["points"] == 0 and players["sam"]["rank"] == 2
    # The challenge began 2 days ago, so a run logged now belongs to its third day.
    assert players["maya"]["ticks"] == [False, False, True]


def test_owner_is_told_why_an_activity_did_not_count(client, challenge):
    fast = client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 30},
                       headers=make_token("maya")).json()
    assert fast["challenges"][0]["counted"] is False and fast["challenges"][0]["reason"] == "impossibly fast"
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    early = client.post("/me/activities", json={"type": "run", "minutes": 30, "start": old},
                        headers=make_token("maya")).json()
    assert early["challenges"][0]["reason"] == "outside the challenge dates"
    assert board(client)["maya"]["points"] == 0


def test_bad_activity_input_is_refused(client, challenge):
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    for body in ({"type": "teleport", "minutes": 30}, {"type": "run", "minutes": 0},
                 {"type": "run", "minutes": 30, "distance_km": -1}):
        assert client.post("/me/activities", json=body, headers=make_token("maya")).status_code == 422
    assert client.post("/me/activities", json={"type": "run", "minutes": 30, "start": future},
                       headers=make_token("maya")).status_code == 400


def test_ties_share_a_rank(client, challenge):
    for who in ("maya", "sam"):
        client.post("/me/activities", json={"type": "walk", "minutes": 25, "distance_km": 2}, headers=make_token(who))
    players = board(client)
    assert players["maya"]["rank"] == players["sam"]["rank"] == 1


def test_leaderboard_shows_points_only_and_only_to_players(client, challenge):
    client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 5}, headers=make_token("maya"))
    assert client.get(f"/challenges/{CHALLENGE}/leaderboard", headers=make_token("zoe")).status_code == 403
    assert client.get(f"/challenges/{CHALLENGE}/leaderboard").status_code == 401
    for player in board(client, "sam").values():
        assert set(player) == {"rank", "name", "points", "ticks", "is_you"}


def test_activities_are_visible_only_to_their_owner(client, challenge):
    client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 5}, headers=make_token("maya"))
    assert len(client.get("/me/activities", headers=make_token("maya")).json()) == 1
    assert client.get("/me/activities", headers=make_token("sam")).json() == []


def test_manual_source_marks_activities_unverified_but_counts_them(client, challenge, monkeypatch):
    monkeypatch.setattr(config, "FITNESS_PROVIDER", "manual")
    body = client.post("/me/activities", json={"type": "walk", "minutes": 40}, headers=make_token("sam")).json()
    assert body["activity"]["verified"] is False and body["activity"]["source_label"] == "Self-reported (unverified)"
    assert body["challenges"][0]["points"] == 1
    with db.SessionLocal() as session:
        assert session.scalars(select(db.ScoreEntry.source)).all() == ["manual"]


def test_switching_source_rescoring_uses_only_that_source(client, challenge, monkeypatch):
    client.post("/me/activities", json={"type": "run", "minutes": 30}, headers=make_token("maya"))
    monkeypatch.setattr(config, "FITNESS_PROVIDER", "manual")
    with db.SessionLocal() as session:
        user = session.scalar(select(db.User).where(db.User.email == "maya@example.com"))
        assert scores.recompute_user(session, user.id)[CHALLENGE].total == 0


def test_scripted_mock_week(client, challenge):
    with db.SessionLocal() as session:
        user = session.scalar(select(db.User).where(db.User.email == "sam@example.com"))
        stored = session.scalar(select(db.Challenge))
        MockProvider().add_script(session, user.id, db.utc(stored.start_time))
        assert scores.recompute(session, stored, user.id).total == 10
        rows = scores.leaderboard(session, stored, now=db.utc(stored.end_time))
    sam = next(r for r in rows if r["name"] == "sam")
    assert sam["points"] == 10 and sam["ticks"] == [True, True, True, False, True, True, False]


def test_disconnect_deletes_activities_and_points(client, challenge):
    client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 5}, headers=make_token("maya"))
    client.post("/me/activities", json={"type": "walk", "minutes": 30}, headers=make_token("sam"))
    assert client.delete("/me/fitness", headers=make_token("maya")).status_code == 200
    assert client.get("/me/activities", headers=make_token("maya")).json() == []
    players = board(client)
    assert players["maya"]["points"] == 0 and players["sam"]["points"] == 1  # still in the pool, score zero


def test_delete_my_workouts_covers_every_in_app_source(client, challenge, monkeypatch):
    """The "Delete my workouts" button: mock and manual workouts share a table, and both go."""
    client.post("/me/activities", json={"type": "run", "minutes": 30}, headers=make_token("maya"))
    monkeypatch.setattr(config, "FITNESS_PROVIDER", "manual")
    client.post("/me/activities", json={"type": "walk", "minutes": 30, "start": (
        datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()}, headers=make_token("maya"))
    with db.SessionLocal() as session:
        assert session.query(db.LoggedActivity).count() == 2
    assert client.delete("/me/fitness", headers=make_token("maya")).status_code == 200
    with db.SessionLocal() as session:
        assert session.query(db.LoggedActivity).count() == 0


# ---------- Stage 5: what the screens need ----------


def add_event(name, data, signature):
    with db.SessionLocal() as session:
        session.add(db.ChainEvent(signature=signature, event_index=0, name=name, challenge=CHALLENGE, slot=1,
                                  data=json.dumps({"challenge": CHALLENGE, **data})))
        session.commit()


def state(client, who="maya"):
    reply = client.get(f"/challenges/{CHALLENGE}/state", headers=make_token(who))
    assert reply.status_code == 200
    return reply.json()


def test_app_config_is_public(client):
    body = client.get("/app-config").json()
    assert body["oracle"] == config.ORACLE_PUBLIC_KEY
    assert body["fitness"]["source"] == "mock" and body["fitness"]["can_add"] is True


def test_challenge_with_another_oracle_is_refused(client, fakes):
    fakes.oracle = WALLETS["zoe"]
    reply = client.post("/challenges", json={"address": CHALLENGE, "name": "Rigged"}, headers=make_token("maya"))
    assert reply.status_code == 400


def test_joining_a_challenge_made_outside_the_app_records_it(client):
    assert client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True},
                       headers=make_token("sam")).status_code == 200
    body = state(client, "sam")
    assert body["challenge"]["name"] == "Weekly challenge" and body["you"]["joined"] is True


def test_name_shows_on_leaderboard_and_in_my_challenges(client, challenge):
    assert client.post("/me/name", json={"name": "  Maya   R "}, headers=make_token("maya")).json()["name"] == "Maya R"
    assert client.post("/me/name", json={"name": "   "}, headers=make_token("maya")).status_code == 400
    assert "Maya R" in board(client)
    mine = client.get("/me/challenges", headers=make_token("maya")).json()
    assert [c["address"] for c in mine] == [CHALLENGE]
    assert client.get("/me/challenges", headers=make_token("zoe")).json() == []


def test_state_before_any_stream_event(client, challenge):
    body = state(client)
    assert body["you"] == {"joined": True, "deposit_confirmed": False, "is_creator": True, "is_admin": False}
    assert body["pool"] is None and body["feed"] == [] and len(body["players"]) == 2


def test_feed_pool_and_deposit_status_come_from_stream_events(client, challenge):
    add_event("ChallengeCreated", {"creator": WALLETS["maya"]}, "s1")
    add_event("PlayerJoined", {"player": WALLETS["maya"], "player_count": 1, "pool_total": 1_000_000}, "s2")
    body = state(client, "sam")
    assert body["you"]["deposit_confirmed"] is False and body["pool"] == 1 and body["player_count"] == 1
    add_event("PlayerJoined", {"player": WALLETS["sam"], "player_count": 2, "pool_total": 2_000_000}, "s3")
    add_event("ChallengeEnded", {"end_time": 1}, "s4")
    add_event("ChallengeSettled", {"winners": [WALLETS["sam"], WALLETS["zoe"]], "pool_total": 2_000_000,
                                   "payout_each": 1_000_000, "score_hash": "00"}, "s5")
    body = state(client, "sam")
    assert body["you"]["deposit_confirmed"] is True and body["pool"] == 0
    assert [item["text"] for item in body["feed"]] == [
        "maya started the challenge",
        "maya joined - pool is now 1 USDC",
        "sam joined - pool is now 2 USDC",
        "The challenge ended",
        "Settled - sam and Player T9re won 1 USDC each",
    ]
    assert body["feed"][1]["signature"] == "s2"


def test_outsiders_see_the_feed_but_not_the_leaderboard(client, challenge):
    add_event("PlayerJoined", {"player": WALLETS["maya"], "player_count": 1, "pool_total": 1_000_000}, "s2")
    body = state(client, "zoe")
    assert body["players"] is None and body["you"]["joined"] is False and len(body["feed"]) == 1


def test_stream_events_update_the_stored_challenge(client, challenge):
    ended_at = int(time.time()) - 60

    def log(name, extra):
        disc = bytes(next(e["discriminator"] for e in chain.IDL["events"] if e["name"] == name))
        return "Program data: " + base64.b64encode(disc + bytes(Pubkey.from_string(CHALLENGE)) + extra).decode()

    winner = struct.pack("<I", 1) + bytes(Pubkey.from_string(WALLETS["sam"]))
    logs = [log("ChallengeEnded", struct.pack("<q", ended_at)),
            log("ChallengeSettled", winner + struct.pack("<QQ", 2_000_000, 2_000_000) + bytes(32))]
    with db.SessionLocal() as session:
        assert events.store_delivery(session, {"transactions": [{"signature": "sig", "slot": 9, "logs": logs}]}) == 2
        stored = session.scalar(select(db.Challenge))
        assert stored.status == "settled" and int(db.utc(stored.end_time).timestamp()) == ended_at
    assert state(client)["feed"][-1]["text"] == "Settled - sam won 2 USDC"


def test_settled_challenges_keep_their_points(client, challenge):
    client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 5}, headers=make_token("maya"))
    with db.SessionLocal() as session:
        session.scalar(select(db.Challenge)).status = "settled"
        session.commit()
    client.post("/me/activities", json={"type": "walk", "minutes": 30, "start": (
        datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()}, headers=make_token("maya"))
    client.delete("/me/fitness", headers=make_token("maya"))
    assert board(client)["maya"]["points"] == 2
