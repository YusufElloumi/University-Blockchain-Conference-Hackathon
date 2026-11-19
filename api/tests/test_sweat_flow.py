"""Proof of Sweat end to end: Oura sync -> checks -> points -> leaderboard -> settlement -> receipts.

Oura and Solana are faked; every workout and heart-rate sample here is synthetic.
"""

import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from cryptography.fernet import Fernet
from solders.keypair import Keypair
from sqlalchemy import select

import attest
import config
import db
import main
import scores
import settlement
import sweat
from fitness import oura, oura_data, oura_sync
from test_stage4 import CHALLENGE, WALLETS, board, challenge, client, fakes, make_token, state  # noqa: F401
from test_stage6 import fake_chain  # noqa: F401

VERIFIER = Keypair()
OTHER = WALLETS["zoe"]  # doubles as the address of a second challenge
NOW = datetime.now(timezone.utc)


class Reply:
    def __init__(self, status, body=None, text=None):
        self.status_code, self._body, self._text = status, body, text

    def json(self):
        if self._text is not None:
            raise ValueError("not JSON")
        return self._body


class FakeOura:
    """Oura's data API for several accounts, keyed by access token."""

    def __init__(self):
        self.workouts: dict[str, list] = {}
        self.heart: dict[str, list] = {}
        self.fail: dict[str, list] = {}  # url -> statuses (or exceptions) to answer with, in order
        self.calls: list[tuple[str, str]] = []
        self.page_size = 50
        self.hold: threading.Event | None = None
        self.entered = threading.Event()

    def get(self, url, params=None, headers=None, timeout=None):
        if url == oura.REVOKE_URL:
            self.calls.append(("revoke", params["access_token"]))
            return Reply(200)
        token = headers["Authorization"][7:]
        self.calls.append((url, token))
        self.entered.set()
        if self.hold:
            self.hold.wait(5)
        queue = self.fail.get(url)
        if queue:
            outcome = queue.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            if isinstance(outcome, Reply):
                return outcome
            if outcome != 200:
                return Reply(outcome, {"detail": "SECRET-DETAIL"})
        if url == oura_data.WORKOUT_URL:
            rows = self.workouts.get(token, [])
            page = int(params.get("next_token") or 0)
            chunk = rows[page * self.page_size:(page + 1) * self.page_size]
            more = (page + 1) * self.page_size < len(rows)
            return Reply(200, {"data": chunk, "next_token": str(page + 1) if more else None})
        lo, hi = params["start_datetime"], params["end_datetime"]
        rows = [r for r in self.heart.get(token, []) if lo <= r["timestamp"] < hi]
        return Reply(200, {"data": rows, "next_token": None})


@pytest.fixture(autouse=True)
def sweat_world(monkeypatch, fake_chain):
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat.TEMPLATE)
    monkeypatch.setattr(config, "SYNC_GRACE_SECONDS", 0)
    monkeypatch.setattr(config, "OURA_CLIENT_ID", "client-123")
    monkeypatch.setattr(config, "OURA_CLIENT_SECRET", "client-secret-xyz")
    monkeypatch.setattr(config, "OURA_REDIRECT_URI", "https://api.example/integrations/oura/callback")
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(oura_sync, "MIN_SYNC_INTERVAL", timedelta(0))
    monkeypatch.setattr(oura_data, "_sleep", lambda seconds: None)
    monkeypatch.setattr(attest, "load_verifier", lambda: VERIFIER)
    monkeypatch.setattr(config, "VERIFIER_PUBLIC_KEY", str(VERIFIER.pubkey()))
    fake = FakeOura()
    monkeypatch.setattr(httpx, "get", fake.get)
    return fake


def link(client, who):
    """Gives a player a working Oura connection (the OAuth flow itself is covered in test_oura.py)."""
    client.get("/integrations/oura", headers=make_token(who))
    with db.SessionLocal() as s:
        user = s.scalar(select(db.User).where(db.User.privy_id == f"did:privy:{who}"))
        oura._save(s, user.id, oura.Tokens(f"tok-{who}", f"refresh-{who}", NOW + timedelta(days=1),
                                           "extapi:workout extapi:heartrate"))
        return user.id


def wk(id="w1", ago=180, minutes=40, activity="running", source="confirmed", **extra):
    """A synthetic Oura workout that started `ago` minutes before now, written with a UTC-6 offset."""
    zone = timezone(timedelta(hours=-6))
    begin = (NOW - timedelta(minutes=ago)).astimezone(zone)
    return {"id": f"oura-id-{id}", "activity": activity, "source": source, "day": begin.date().isoformat(),
            "start_datetime": begin.isoformat(), "end_datetime": (begin + timedelta(minutes=minutes)).isoformat(),
            "intensity": "moderate", "calories": 4321.5, "label": None, **extra}


def beats(workout, minutes=None, source="workout", bpm=147.25):  # an unmistakable value to search for
    """One heart-rate sample a minute across (the first `minutes` of) a workout."""
    begin = datetime.fromisoformat(workout["start_datetime"]).astimezone(timezone.utc)
    end = datetime.fromisoformat(workout["end_datetime"]).astimezone(timezone.utc)
    count = int((end - begin).total_seconds() // 60) if minutes is None else minutes
    return [{"timestamp": (begin + timedelta(minutes=m, seconds=5)).isoformat(), "bpm": bpm, "source": source}
            for m in range(count)]


def sync(client, who="maya"):
    return client.post("/integrations/oura/sync", headers=make_token(who))


def mine(client, who="maya", address=CHALLENGE):
    reply = client.get(f"/me/sweat?challenge={address}", headers=make_token(who))
    assert reply.status_code == 200, reply.text
    return reply.json()


def rows(user_id=None):
    with db.SessionLocal() as s:
        query = select(db.ImportedActivity).order_by(db.ImportedActivity.id)
        return list(s.scalars(query if user_id is None else query.where(db.ImportedActivity.user_id == user_id)))


# ---------- import, checks and points ----------


def test_a_real_looking_workout_becomes_verified_points(client, challenge, sweat_world):
    link(client, "maya")
    run = wk(minutes=40, distance=6200.0)
    sweat_world.workouts["tok-maya"], sweat_world.heart["tok-maya"] = [run], beats(run)
    reply = sync(client)
    assert reply.status_code == 200
    assert {k: reply.json()[k] for k in ("found", "new", "verified", "pending", "rejected")} == {
        "found": 1, "new": 1, "verified": 1, "pending": 0, "rejected": 0}
    assert board(client)["maya"]["points"] == 4 and board(client)["sam"]["points"] == 0

    view = mine(client)
    assert view["points"] == 4 and view["eligible_minutes"] == 40 and view["rules"]["version"] == "proof-of-sweat-v1"
    [workout] = view["workouts"]
    assert (workout["activity"], workout["result"], workout["assurance"], workout["points"]) == ("run", "verified", "strong", 4)
    assert workout["provider_source"] == "confirmed" and workout["heart_rate_coverage_pct"] == 100
    assert {c["code"]: c["result"] for c in workout["checks"]} == {
        "provider": "passed", "provenance": "passed", "activity": "passed", "timestamps": "passed",
        "duration": "passed", "plausibility": "passed", "evidence": "passed", "window": "passed",
        "duplicate": "passed", "scoring": "passed"}

    [row] = rows()
    assert "oura-id" not in row.provider_ref and row.intensity == "moderate"
    assert (row.hr_bins_total, row.hr_bins_covered) == (40, 40)
    stored = json.dumps({c.name: str(getattr(row, c.name)) for c in row.__table__.columns})
    assert "147.25" not in stored and "4321.5" not in stored  # no heart-rate readings and no calories
    assert not [c.name for c in row.__table__.columns if "bpm" in c.name or "calor" in c.name or "series" in c.name]
    assert row.hr_median == 147  # one summary number per workout (the middle value), used by v2's effort factor


def test_syncing_again_never_adds_rows_or_points(client, challenge, sweat_world):
    link(client, "maya")
    run = wk()
    sweat_world.workouts["tok-maya"], sweat_world.heart["tok-maya"] = [run, dict(run)], beats(run)
    for _ in range(3):
        assert sync(client).status_code == 200
    assert len(rows()) == 1 and board(client)["maya"]["points"] == 4
    assert sync(client).json()["new"] == 0
    heart_calls = [c for c in sweat_world.calls if c[0] == oura_data.HEARTRATE_URL]
    assert len(heart_calls) == 1  # heart rate is read once per workout, not on every sync


def test_no_heart_rate_is_limited_evidence_but_full_points(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk("a", ago=400, minutes=30), wk("b", ago=200, minutes=30)]
    sweat_world.heart["tok-maya"] = beats(wk("b", ago=200, minutes=30), minutes=5)
    sync(client)
    found = {w["duration_minutes"] and w["reason"]: w for w in mine(client)["workouts"]}
    assert set(found) == {"no_heart_rate", "low_coverage"}
    assert all(w["result"] == "verified" and w["assurance"] == "limited" and w["points"] == 3 for w in found.values())
    assert board(client)["maya"]["points"] == 6


@pytest.mark.parametrize("workout, reason", [
    (wk(source="manual"), "manual_entry"),
    (wk(source="mystery_feed"), "unknown_source"),
    (wk(activity="houseWork"), "unsupported_activity"),
    (wk(minutes=8), "under_minimum"),
    (wk(minutes=30, distance=40000.0), "too_fast"),
    (wk(start_datetime="nonsense"), "missing_time"),
])
def test_ineligible_workouts_are_rejected_with_the_reason(client, challenge, sweat_world, workout, reason):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [workout]
    assert sync(client).json()["rejected"] == 1
    assert board(client)["maya"]["points"] == 0
    [row] = rows()
    assert (row.status, row.reason) == ("rejected", reason)
    assert not [c for c in sweat_world.calls if c[0] == oura_data.HEARTRATE_URL]  # no heart rate read for these


def test_automatically_detected_and_missing_distance_are_fine(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk(source="autodetected", activity="walking", minutes=25)]
    sync(client)
    assert board(client)["maya"]["points"] == 2 and rows()[0].distance_km is None


def test_overlapping_and_out_of_window_time_is_not_credited(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [
        wk("a", ago=300, minutes=30), wk("b", ago=285, minutes=30),  # 45 minutes between them
        wk("old", ago=4 * 24 * 60, minutes=60),  # before the challenge started (it began 2 days ago)
    ]
    sync(client)
    view = mine(client)
    assert view["points"] == 4 and view["eligible_minutes"] == 45 and len(view["workouts"]) == 2
    assert len(rows()) == 3  # imported, but only credited where it falls inside the challenge


def test_the_same_workout_counts_in_two_challenges_once_each(client, challenge, sweat_world):
    client.post("/challenges", json={"address": OTHER, "name": "Second", "mode": "public"}, headers=make_token("maya"))
    client.post(f"/challenges/{OTHER}/join", json={"consent": True}, headers=make_token("maya"))
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client), sync(client)
    assert len(rows()) == 1
    assert mine(client)["points"] == 4 and mine(client, address=OTHER)["points"] == 4
    with db.SessionLocal() as s:
        entries = list(s.scalars(select(db.ScoreEntry)))
    assert sorted(e.points for e in entries) == [4, 4] and {e.source for e in entries} == {"oura"}


def test_one_oura_workout_cannot_be_credited_to_two_rival_accounts(client, challenge, sweat_world):
    link(client, "maya"), link(client, "sam")
    sweat_world.workouts["tok-maya"] = sweat_world.workouts["tok-sam"] = [wk()]
    sync(client, "maya")
    assert sync(client, "sam").json()["skipped"] == 1
    assert board(client)["maya"]["points"] == 4 and board(client)["sam"]["points"] == 0 and len(rows()) == 1


def test_a_player_without_oura_earns_nothing_and_is_told_so(client, challenge):
    assert sync(client, "sam").status_code == 404
    view = mine(client, "sam")
    assert view["connected"] is False and view["points"] == 0 and view["workouts"] == []
    link(client, "maya")
    players = {p["name"]: p["oura"] for p in state(client)["players"]}
    assert players == {"maya": "waiting", "sam": "none"}  # linked but not synced yet / not linked


# ---------- the old manual route cannot earn Proof of Sweat points ----------


def test_hand_entered_workouts_never_score_and_cannot_be_backdated(client, challenge):
    reply = client.post("/me/activities", json={"type": "run", "minutes": 60, "distance_km": 10}, headers=make_token("maya"))
    assert reply.status_code == 200 and reply.json()["activity"]["verified"] is False
    assert reply.json()["challenges"] == [{"address": CHALLENGE, "name": "Office week", "points": 0, "counted": False,
                                           "reason": "this challenge only counts workouts synced from Oura"}]
    assert board(client)["maya"]["points"] == 0
    old = (NOW - timedelta(hours=5)).isoformat()
    assert client.post("/me/activities", json={"type": "run", "minutes": 60, "start": old},
                       headers=make_token("maya")).status_code == 400
    listed = client.get(f"/me/activities?challenge={CHALLENGE}", headers=make_token("maya")).json()
    assert [a["status"] for a in listed] == ["rejected"]


def test_clients_cannot_supply_statuses_points_or_sources(client, challenge):
    forged = {"type": "run", "minutes": 60, "verified": True, "status": "verified", "points": 99,
              "provider_source": "confirmed", "assurance": "strong"}
    assert client.post("/me/activities", json=forged, headers=make_token("maya")).status_code == 200
    assert board(client)["maya"]["points"] == 0 and rows() == []
    assert client.post("/integrations/oura/sync", json=forged).status_code == 401  # no login, no sync
    assert client.get(f"/me/sweat?challenge={CHALLENGE}").status_code == 401


def test_receipts_are_only_for_players_of_that_challenge(client, challenge):
    assert client.get(f"/me/sweat?challenge={CHALLENGE}", headers=make_token("zoe")).status_code == 404


# ---------- edits, deletions, provider trouble ----------


def test_an_edit_at_the_provider_is_checked_again(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    assert board(client)["maya"]["points"] == 4
    sweat_world.workouts["tok-maya"] = [wk(source="manual")]  # same ID, now hand-entered
    assert sync(client).json()["updated"] == 1
    assert board(client)["maya"]["points"] == 0 and rows()[0].reason == "manual_entry" and len(rows()) == 1


def test_a_workout_must_be_missing_twice_before_it_is_dropped(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    sweat_world.workouts["tok-maya"] = []
    sync(client)
    assert board(client)["maya"]["points"] == 4  # one absence proves nothing
    sync(client)
    assert board(client)["maya"]["points"] == 0 and rows()[0].reason == "removed_at_provider"
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    assert board(client)["maya"]["points"] == 4  # it came back


def test_a_partial_listing_never_counts_as_a_deletion(client, challenge, sweat_world, monkeypatch):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk("a", ago=300), wk("b", ago=200), wk("c", ago=100)]
    sweat_world.page_size = 1
    assert sync(client).json() | {} and len(rows()) == 3  # three pages followed
    monkeypatch.setattr(oura_sync, "MAX_WORKOUT_PAGES", 1)
    for _ in range(3):
        assert sync(client).json()["complete"] is False
    assert all(r.status == "verified" for r in rows())


def test_timeouts_and_rate_limits_are_retried_then_reported(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sweat_world.fail[oura_data.WORKOUT_URL] = [httpx.ReadTimeout("slow"), 429]  # then it works
    assert sync(client).status_code == 200 and board(client)["maya"]["points"] == 4
    sweat_world.fail[oura_data.WORKOUT_URL] = [429, 429, 429]
    reply = sync(client)
    assert reply.status_code == 429 and "SECRET" not in reply.text
    status = client.get("/integrations/oura", headers=make_token("maya")).json()
    assert status["last_sync_error"] == "rate_limited" and status["last_sync_at"]
    assert board(client)["maya"]["points"] == 4  # an outage never removes points
    assert sync(client).status_code == 200
    assert client.get("/integrations/oura", headers=make_token("maya")).json()["last_sync_error"] is None


def test_malformed_replies_do_not_import_anything(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.fail[oura_data.WORKOUT_URL] = [Reply(200, text="<html>")]
    assert sync(client).status_code == 502
    sweat_world.fail[oura_data.WORKOUT_URL] = [Reply(200, {"data": "nope"})]
    assert sync(client).status_code == 502
    sweat_world.workouts["tok-maya"] = ["junk", {"no": "id"}, {"id": 5}, wk()]
    reply = sync(client).json()
    assert (reply["found"], reply["skipped"]) == (1, 3) and len(rows()) == 1


def test_revoked_access_ends_cleanly(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.fail[oura_data.WORKOUT_URL] = [401]
    assert sync(client).status_code == 401
    assert client.get("/integrations/oura", headers=make_token("maya")).json()["last_sync_error"] == "reconnect"


def test_an_expiring_token_is_refreshed_before_syncing(client, challenge, sweat_world, monkeypatch):
    user_id = link(client, "maya")
    with db.SessionLocal() as s:
        s.scalar(select(db.FitnessConnection)).token_expires_at = NOW + timedelta(minutes=1)
        s.commit()
    monkeypatch.setattr(oura, "_token_request", lambda form: oura.Tokens("tok-fresh", "refresh-2", NOW + timedelta(days=1), None))
    sweat_world.workouts["tok-fresh"] = [wk()]
    assert sync(client).json()["new"] == 1 and rows(user_id)


def test_missing_heart_rate_permission_still_verifies_as_limited(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk("a", ago=300), wk("b", ago=200)]
    sweat_world.fail[oura_data.HEARTRATE_URL] = [403]
    sync(client)
    assert {(r.status, r.assurance, r.reason) for r in rows()} == {("verified", "limited", "heart_rate_unavailable")}
    assert len([c for c in sweat_world.calls if c[0] == oura_data.HEARTRATE_URL]) == 1


def test_heart_rate_trouble_leaves_a_workout_pending_then_limited(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sweat_world.fail[oura_data.HEARTRATE_URL] = [500] * 6  # two syncs' worth of retries
    assert sync(client).json()["pending"] == 1
    assert board(client)["maya"]["points"] == 0  # pending never scores
    assert mine(client)["workouts"][0]["result"] == "pending"
    sync(client)
    sweat_world.fail[oura_data.HEARTRATE_URL] = [500] * 3
    sync(client)  # third failed attempt: stop waiting
    assert (rows()[0].status, rows()[0].reason) == ("verified", "heart_rate_unavailable")
    assert board(client)["maya"]["points"] == 4


# ---------- rate limiting and concurrency ----------


def test_manual_sync_is_rate_limited(client, challenge, monkeypatch):
    link(client, "maya")
    monkeypatch.setattr(oura_sync, "MIN_SYNC_INTERVAL", timedelta(seconds=30))
    assert sync(client).status_code == 200
    assert sync(client).status_code == 429


def test_two_syncs_at_once_do_not_both_run(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sweat_world.hold = threading.Event()
    first = {}
    thread = threading.Thread(target=lambda: first.update(reply=sync(client)))
    thread.start()
    assert sweat_world.entered.wait(5)
    assert sync(client).status_code == 409  # the second request is turned away while the first is talking to Oura
    sweat_world.hold.set()
    thread.join(10)
    assert first["reply"].status_code == 200 and len(rows()) == 1 and board(client)["maya"]["points"] == 4


def test_recomputing_twice_stores_one_set_of_points(client, challenge, sweat_world):
    user_id = link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    with db.SessionLocal() as s:
        found = s.scalar(select(db.Challenge))
        for _ in range(3):
            scores.recompute(s, found, user_id)
        entries = list(s.scalars(select(db.ScoreEntry).where(db.ScoreEntry.user_id == user_id)))
    assert [(e.day, e.points) for e in entries] == [(1, 4)]


def test_a_recompute_that_loses_a_race_does_not_duplicate_or_fail(client, challenge, sweat_world, monkeypatch):
    user_id = link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    with db.SessionLocal() as s:
        found = s.scalar(select(db.Challenge))
        # Pretend another request stored the same day between our delete and our insert.
        real = s.flush
        def racing_commit():
            with db.SessionLocal() as other:
                other.add(db.ScoreEntry(challenge_id=found.id, user_id=user_id, day=1, points=4, active=True,
                                        source="oura", source_activity_ids="[]"))
                try:
                    other.commit()
                except Exception:
                    other.rollback()
        s.execute(db.ScoreEntry.__table__.delete())
        s.commit()
        racing_commit()
        scores.recompute(s, found, user_id)
    assert board(client)["maya"]["points"] == 4


# ---------- settlement, the score sheet and receipts ----------


def end(fakes, minutes_ago=1):
    """Ends the pretend challenge, and makes every earlier sync predate that end."""
    fakes.end_time = int(time.time()) - minutes_ago * 60
    with db.SessionLocal() as s:
        for connection in s.scalars(select(db.FitnessConnection)):
            if connection.last_sync_at:
                connection.last_sync_at = NOW - timedelta(days=1)
        s.commit()


def finish(client, who="maya"):
    return client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token(who))


def settle(client, fakes, sweat_world):
    """Maya: 40 verified minutes with strong evidence, 30 with none (70 in one day: capped at 6 points),
    and one manual entry. Sam: not connected."""
    link(client, "maya")
    strong = wk("strong", ago=300, minutes=40, distance=6000.0)
    sweat_world.workouts["tok-maya"] = [strong, wk("bare", ago=200, minutes=30), wk("typed", ago=100, source="manual")]
    sweat_world.heart["tok-maya"] = beats(strong)
    sync(client)
    end(fakes)
    reply = finish(client)
    assert reply.status_code == 200 and reply.json()["action"] == "settled", reply.text
    return client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()


def test_settlement_waits_for_the_sync_grace_period(client, challenge, fakes, sweat_world, monkeypatch):
    monkeypatch.setattr(config, "SYNC_GRACE_SECONDS", 1800)
    link(client, "maya")
    end(fakes, minutes_ago=5)
    reply = finish(client)
    assert reply.status_code == 409 and "final workout syncs" in reply.json()["detail"]
    shown = state(client)["sweat"]
    assert shown["awaiting_final_sync"] is True and shown["grace_seconds"] == 1800
    end(fakes, minutes_ago=31)
    assert finish(client).json()["action"] == "settled"


def test_a_final_sync_runs_before_scores_are_fixed(client, challenge, fakes, fake_chain, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]  # never synced by the player
    end(fakes)
    assert finish(client).json()["winners"] == [WALLETS["maya"]]
    sheet = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()["sheet"]
    assert sheet["scores"] == [{"wallet": WALLETS["maya"], "points": 4}, {"wallet": WALLETS["sam"], "points": 0}]
    assert [p["sync"] for p in sheet["proof_of_sweat"]["participants"]] == ["complete", "not_connected"]


def test_an_oura_outage_delays_settlement_but_never_forever(client, challenge, fakes, fake_chain, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    end(fakes)
    sweat_world.fail[oura_data.WORKOUT_URL] = [500] * 9
    for _ in range(oura_sync.MAX_FINAL_SYNC_ATTEMPTS):
        assert finish(client).status_code == 409  # waiting, not settling on a guess
    assert not [sent for sent in fake_chain if sent[0] == "settle"]
    reply = finish(client)
    assert reply.json()["action"] == "settled"  # tries used up: settle on what was already verified
    sheet = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()["sheet"]
    assert sheet["scores"][0]["points"] == 4  # the outage neither added nor removed points
    assert sheet["proof_of_sweat"]["participants"][0]["sync"] == "unavailable"


def test_the_wait_for_syncs_has_a_deadline(client, challenge, fakes, sweat_world, monkeypatch):
    link(client, "maya")
    monkeypatch.setattr(config, "SYNC_GIVE_UP_SECONDS", 60)
    sweat_world.fail[oura_data.WORKOUT_URL] = [500] * 3
    end(fakes, minutes_ago=2)
    assert finish(client).json()["action"] == "settled"


def test_admin_end_now_still_syncs_first(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.json()["action"] == "settled" and reply.json()["winners"] == [WALLETS["maya"]]


def test_the_onchain_hash_covers_the_sheet_with_its_receipt_commitments(client, challenge, fakes, fake_chain, sweat_world):
    published = settle(client, fakes, sweat_world)
    sheet = published["sheet"]
    assert sheet["rules"] == "proof_of_sweat_v1" and sheet["rules_version"] == "proof-of-sweat-v1"
    assert sheet["rules_sha256"] == sweat.rules_fingerprint()
    maya, sam = sheet["proof_of_sweat"]["participants"]
    assert (maya["wallet"], maya["eligible_minutes"], maya["fitness_points"]) == (WALLETS["maya"], 70, 6)
    assert len(maya["receipts"]) == 3 and maya["receipts"] == sorted(maya["receipts"]) and sam["receipts"] == []
    recomputed = hashlib.sha256(published["canonical"].encode()).digest()
    assert fake_chain[-1][0] == "settle" and fake_chain[-1][2] == recomputed  # what the program stored
    assert json.loads(published["canonical"]) == sheet


def test_nothing_private_is_in_the_sheet_the_proof_or_the_transaction(client, challenge, fakes, fake_chain, sweat_world):
    published = settle(client, fakes, sweat_world)
    public = json.dumps([published, [str(part) for part in fake_chain[-1]]])
    for private in ("oura-id", "147.25", "4321.5", "start_datetime", "confirmed", "running", "6000.0", "6.0", "bpm",
                    "tok-maya", "moderate"):
        assert private not in public
    # Not even the workout's start time, in any spelling.
    with db.SessionLocal() as s:
        assert s.scalar(select(db.ImportedActivity.start_time)).isoformat()[:13] not in public


def test_the_signed_proof_binds_the_receipts(client, challenge, fakes, sweat_world):
    published = settle(client, fakes, sweat_world)
    proof, sheet = published["proof"], published["sheet"]
    # v2 proof (locked rules): the signed bytes name the score-sheet hash, which covers every receipt
    # commitment; Solana checks that signature at payout. The readable summary is recomputed on checking.
    assert proof["schema"] == 2 and proof["proof_of_sweat"]["receipts"] == 3
    assert published["proof_problems"] == [] == attest.check_v2(proof, challenge=CHALLENGE, sheet=sheet)

    changed = json.loads(json.dumps(sheet))
    changed["scores"][1]["points"] = 99
    assert "the score sheet does not match the signed hash" in attest.check_v2(proof, challenge=CHALLENGE, sheet=changed)
    swapped = json.loads(json.dumps(sheet))
    swapped["proof_of_sweat"]["participants"][0]["receipts"][0] = "0" * 64
    problems = attest.check_v2(proof, challenge=CHALLENGE, sheet=swapped)
    assert "the score sheet does not match the signed hash" in problems
    assert "the workout receipt commitments do not match the summary" in problems
    assert attest.check_v2(proof, challenge=OTHER, sheet=sheet)  # cannot be replayed for another challenge


def test_owners_get_receipts_that_match_the_committed_hashes(client, challenge, fakes, sweat_world):
    published = settle(client, fakes, sweat_world)
    committed = published["sheet"]["proof_of_sweat"]["participants"][0]["receipts"]
    view = mine(client)
    assert view["final"] is True and view["points"] == 6 and len(view["receipts"]) == 3
    for item in view["receipts"]:
        assert hashlib.sha256(item["canonical"].encode()).hexdigest() == item["commitment"] and item["commitment"] in committed
        receipt = item["receipt"]
        assert receipt["challenge"] == CHALLENGE and receipt["wallet"] == WALLETS["maya"] and len(receipt["salt"]) == 32
        assert receipt["domain"] == "rival.proof-of-sweat.receipt" and receipt["rules_sha256"] == sweat.rules_fingerprint()
        assert "oura-id" not in item["canonical"] and "T" not in "".join(str(v) for v in receipt["days"].values())
    by_result = sorted((r["receipt"]["result"], r["receipt"]["assurance"], r["receipt"]["points"]) for r in view["receipts"])
    assert by_result == [("rejected", None, 0), ("verified", "limited", 2), ("verified", "strong", 4)]  # 4 + 2: the daily cap
    tampered = view["receipts"][0]["canonical"].replace('"points":', '"points":1')
    assert hashlib.sha256(tampered.encode()).hexdigest() not in committed
    assert mine(client, "sam")["receipts"] == []  # Sam sees his own (none), never Maya's


def test_settled_scores_never_change_and_cannot_settle_twice(client, challenge, fakes, fake_chain, sweat_world):
    settle(client, fakes, sweat_world)
    sweat_world.workouts["tok-maya"].append(wk("late", ago=50, minutes=60))
    sync(client)
    assert board(client)["maya"]["points"] == 6
    assert finish(client).json()["action"] == "none"
    assert len([sent for sent in fake_chain if sent[0] == "settle"]) == 1


def test_pending_workouts_are_not_finalized_as_points(client, challenge, fakes, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sweat_world.fail[oura_data.HEARTRATE_URL] = [500] * 3
    sync(client)  # the workout is pending
    end(fakes)
    sweat_world.fail[oura_data.HEARTRATE_URL] = [500] * 3
    assert finish(client).status_code == 409  # still pending after the final sync: wait
    assert finish(client).json()["action"] == "settled"  # heart rate available now
    assert mine(client)["points"] == 4


def test_too_few_players_still_refunds(client, challenge, fakes):
    fakes.players = fakes.players[:1]
    assert finish(client).json()["action"] == "refunded"


# ---------- rule sets side by side ----------


def test_earlier_challenges_keep_their_rules(client, sweat_world, monkeypatch):
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", "daily_mover")
    body = client.post("/challenges", json={"address": CHALLENGE, "name": "Old", "mode": "public"},
                       headers=make_token("maya")).json()
    assert body["template"] == "daily_mover" and body["rules"]["proof_of_sweat"] is False
    client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True}, headers=make_token("maya"))
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat.TEMPLATE)  # the server is now on Proof of Sweat
    new = client.post("/challenges", json={"address": OTHER, "name": "New", "mode": "public"}, headers=make_token("maya")).json()
    assert new["template"] == "proof_of_sweat_v1" and new["rules"]["summary"] == sweat.SUMMARY
    client.post("/me/activities", json={"type": "run", "minutes": 30, "distance_km": 5}, headers=make_token("maya"))
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    assert board(client)["maya"]["points"] == 2  # the old challenge: old formula, old source, untouched by Oura
    assert client.get(f"/me/sweat?challenge={CHALLENGE}", headers=make_token("maya")).status_code == 404
    assert state(client)["sweat"] is None


def test_league_stat_events_are_not_proof_of_sweat(client):
    body = client.post("/challenges", json={"address": CHALLENGE, "name": "League", "mode": "league",
                                            "organizer_name": "FC", "scoring_source": "league_stats"},
                       headers=make_token("maya")).json()
    assert body["rules"]["name"] == "league_stats" and body["rules"]["proof_of_sweat"] is False


# ---------- disconnect, deletion, retention ----------


def test_disconnecting_revokes_deletes_and_removes_unfinished_points(client, challenge, sweat_world):
    link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk()]
    sync(client)
    reply = client.delete("/integrations/oura", headers=make_token("maya")).json()
    assert reply["revoked"] is True and reply["connected"] is False and ("revoke", "tok-maya") in sweat_world.calls
    assert rows() == [] and board(client)["maya"]["points"] == 0
    assert sync(client).status_code == 404  # no further syncing


def test_delete_my_fitness_data_also_revokes_oura(client, challenge, fakes, sweat_world):
    settle(client, fakes, sweat_world)
    reply = client.delete("/me/fitness", headers=make_token("maya")).json()
    assert reply == {"disconnected": True, "oura_revoked": True} and ("revoke", "tok-maya") in sweat_world.calls
    with db.SessionLocal() as s:
        assert not list(s.scalars(select(db.ImportedActivity))) and not list(s.scalars(select(db.SweatReceipt)))
        assert not list(s.scalars(select(db.FitnessConnection)))
        assert s.scalar(select(db.Challenge)).score_sheet  # the finished result itself stays


def test_cleanup_deletes_what_no_recent_challenge_needs(client, challenge, fakes, sweat_world):
    user_id = link(client, "maya")
    sweat_world.workouts["tok-maya"] = [wk("in", ago=200), wk("before", ago=20 * 24 * 60)]
    sync(client)
    later = NOW + timedelta(days=8)  # both are older than 7 days by then
    with db.SessionLocal() as s:
        assert oura_sync.cleanup(s, now=later) == 1  # the one outside any challenge goes; the challenge is still open
        assert [r.status for r in s.scalars(select(db.ImportedActivity))] == ["verified"]
        found = s.scalar(select(db.Challenge))
        found.status, found.end_time = "settled", NOW
        s.commit()
        assert oura_sync.cleanup(s, now=NOW + timedelta(days=6)) == 0  # ended under 7 days ago: kept
        assert oura_sync.cleanup(s, now=later) == 1
    assert rows(user_id) == []


def test_the_scheduler_runs_the_cleanup(client, challenge, monkeypatch):
    ran = []
    monkeypatch.setattr(oura_sync, "cleanup", lambda session: ran.append(1))
    monkeypatch.setattr(config, "TICK_SECRET", "s3cret")
    assert client.post("/internal/tick", headers={"X-Tick-Secret": "s3cret"}).status_code == 200 and ran == [1]


# ---------- logs ----------


def test_no_workout_or_heart_rate_data_reaches_the_logs(client, challenge, fakes, sweat_world, caplog):
    caplog.set_level(logging.DEBUG)
    settle(client, fakes, sweat_world)
    sweat_world.fail[oura_data.WORKOUT_URL] = [500, 500, 500]
    sync(client)
    for private in ("oura-id", "147.25", "4321.5", "running", "tok-maya", "refresh-maya", "SECRET-DETAIL", "6000.0"):
        assert private not in caplog.text
