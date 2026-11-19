"""Proof of Sweat v2 end to end: sync -> Evidence Index and effort-weighted Sweat Points -> leaderboard ->
settlement receipts. Oura and Solana are faked; every workout and heart-rate value is synthetic."""

import hashlib
import json
import logging
from datetime import timedelta

import pytest
from sqlalchemy import select

import attest
import config
import db
import rules
import scores
import sweat
import sweat2
from fitness import oura_data, oura_sync
from test_stage4 import CHALLENGE, WALLETS, board, challenge, client, fakes, make_token, state  # noqa: F401
from test_stage6 import fake_chain  # noqa: F401
from test_sweat_flow import NOW, OTHER, beats, end, finish, link, mine, rows, sweat_world, sync, wk  # noqa: F401


@pytest.fixture(autouse=True)
def v2(monkeypatch, sweat_world):
    """New challenges use Proof of Sweat v2 (the production default)."""
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat2.TEMPLATE)
    return sweat_world


DAY = 24 * 60


def history(world, who="maya", bpm=140.4, count=5):
    """Earlier workouts (before the challenge began 2 days ago) with full exercise heart rate: the reference."""
    past = [wk(f"past{i}", ago=(3 + i) * DAY, minutes=30) for i in range(count)]
    world.workouts.setdefault(f"tok-{who}", []).extend(past)
    world.heart.setdefault(f"tok-{who}", []).extend(s for w in past for s in beats(w, bpm=bpm))
    return past


def only(client, who="maya", address=CHALLENGE):
    [workout] = mine(client, who, address)["workouts"]
    return workout


# ---------- scoring ----------


def test_a_plain_workout_scores_its_minutes_with_limited_evidence(client, challenge, v2):
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk(minutes=40, activity="strengthTraining")]  # moderate, no heart rate, no distance
    sync(client)
    assert board(client)["maya"]["points"] == 40
    view = mine(client)
    assert view["rules"]["version"] == "proof-of-sweat-v2" and view["rules"]["generation"] == 2
    assert view["days"] == [{"day": 1, "minutes": 40, "points": 40, "effective_minutes": "40.00"}]
    workout = view["workouts"][0]
    assert (workout["result"], workout["assurance"], workout["points"]) == ("verified", "limited", 40.0)
    detail = workout["v2"]
    assert detail["evidence"]["index"] == 67 and detail["evidence"]["limits"] == ["no_heart_rate"]
    assert detail["score"]["multiplier"] == "1.000" and detail["score"]["effective_minutes"] == "40.00"
    states = {k: (f["value"], f["state"], f["reason"]) for k, f in detail["score"]["factors"].items()}
    assert states == {"provider": ("1.00", "provider_estimated", "moderate"),
                      "heart": ("1.00", "unavailable", "no_heart_rate"),
                      "movement": ("1.00", "unavailable", "no_pace_for_category")}


def test_a_hard_fast_run_above_your_own_reference_scores_more(client, challenge, v2):
    link(client, "maya")
    history(v2)
    run = wk("run", ago=300, minutes=40, intensity="hard", distance=7400.0)  # 11.1 km/h
    v2.workouts["tok-maya"].append(run)
    v2.heart["tok-maya"].extend(beats(run, bpm=154.3))  # about 10% above the reference
    sync(client)
    workout = only(client)
    score = workout["v2"]["score"]
    assert {k: f["value"] for k, f in score["factors"].items()} == {"provider": "1.12", "heart": "1.125", "movement": "1.05"}
    assert score["multiplier"] == "1.108" and score["contribution"] == "44.32" and workout["points"] == 44.32
    assert score["factors"]["heart"]["relative_percent"] == 10 and score["factors"]["heart"]["reference_workouts"] == 5
    assert score["factors"]["movement"]["speed_kmh"] == 11.1
    assert workout["assurance"] == "strong" and workout["v2"]["evidence"]["index"] == 100
    assert board(client)["maya"]["points"] == 44
    reply = client.get(f"/me/sweat?challenge={CHALLENGE}", headers=make_token("maya")).text
    for private in ("154", "140", "bpm", "hr_median", '"median"'):  # effort is shown as a relative %, never as a pulse
        assert private not in reply
    assert mine(client)["reference"] == {"frozen": True, "available": True, "workouts": 5}


def test_an_easy_walk_earns_real_credit_but_less(client, challenge, v2):
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk(minutes=40, activity="walking", intensity="easy", distance=3000.0)]  # 4.5 km/h
    sync(client)
    workout = only(client)
    score, evidence = workout["v2"]["score"], workout["v2"]["evidence"]
    assert score["multiplier"] == "0.960" and evidence["index"] == 75 and score["reliability"] == "0.85"
    # Base 40; the easy label would take 1.60 off; with 85% reliability it takes 1.36.
    assert (score["base_points"], score["potential_bonus"], score["adjusted_bonus"], score["contribution"]) == (
        "40.00", "-1.60", "-1.36", "38.64")
    assert board(client)["maya"]["points"] == 39


def test_long_days_taper_and_two_workouts_share_the_days_bands(client, challenge, v2):
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk("long", ago=400, minutes=90)]
    sync(client)
    assert board(client)["maya"]["points"] == 78
    assert only(client)["v2"]["score"]["band_minutes"] == [60.0, 30.0, 0.0, 0.0]
    link(client, "sam")
    v2.workouts["tok-sam"] = [wk("am", ago=500, minutes=45), wk("pm", ago=300, minutes=45)]
    sync(client, "sam")
    assert board(client, "sam")["sam"]["points"] == 78  # 45 + 15 full, then 30 x 0.6: not 90
    assert sorted(w["points"] for w in mine(client, "sam")["workouts"]) == [33.0, 45.0]


def test_syncing_again_changes_nothing(client, challenge, v2):
    link(client, "maya")
    history(v2)
    v2.workouts["tok-maya"].append(wk(minutes=40))
    sync(client)
    before = mine(client)
    for _ in range(3):
        sync(client)
    after = mine(client)
    assert after["workouts"] == before["workouts"] and after["points"] == before["points"] == 40
    assert len(rows()) == 6


# ---------- evidence decides how much of the effort bonus counts ----------


def test_a_hard_label_with_no_supporting_heart_rate_keeps_base_and_a_reduced_bonus(client, challenge, v2):
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk(minutes=40, activity="strengthTraining", intensity="hard")]
    sync(client)
    detail = only(client)["v2"]
    score = detail["score"]
    assert detail["evidence"]["index"] == 67 and detail["evidence"]["reliability"] == "0.65"
    assert (score["base_points"], score["potential_bonus"], score["adjusted_bonus"], score["contribution"]) == (
        "40.00", "1.92", "1.25", "41.25")
    assert {k: f["bonus"] for k, f in score["factors"].items()} == {"provider": "1.92", "heart": "0.00", "movement": "0.00"}
    assert board(client)["maya"]["points"] == 41


def test_the_same_effort_earns_more_bonus_when_the_evidence_is_stronger(client, challenge, v2):
    """Two players, the same hard 40-minute session by Oura's label. One has full exercise heart rate
    (but no history, so the heart factor itself is neutral for both); the other has none."""
    link(client, "maya"), link(client, "sam")
    recorded, bare = wk("m", minutes=40, intensity="hard"), wk("s", minutes=40, intensity="hard")
    v2.workouts["tok-maya"], v2.heart["tok-maya"] = [recorded], beats(recorded, bpm=171.6)
    v2.workouts["tok-sam"] = [bare]
    sync(client, "maya"), sync(client, "sam")
    strong, weak = only(client, "maya")["v2"], only(client, "sam")["v2"]
    assert strong["score"]["potential_bonus"] == weak["score"]["potential_bonus"] == "1.92"  # same effort signals
    assert strong["score"]["base_points"] == weak["score"]["base_points"] == "40.00"  # same base
    assert (strong["evidence"]["index"], weak["evidence"]["index"]) == (92, 67)
    assert (strong["score"]["adjusted_bonus"], weak["score"]["adjusted_bonus"]) == ("1.92", "1.25")
    assert only(client, "maya")["v2"]["score"]["factors"]["heart"]["value"] == "1.00"  # a high pulse added nothing


def test_points_agree_across_receipt_leaderboard_and_day_totals(client, challenge, v2):
    link(client, "maya")
    history(v2)
    run = wk("run", ago=300, minutes=40, intensity="hard", distance=7400.0)
    v2.workouts["tok-maya"] += [run, wk("walk", ago=150, minutes=30, activity="walking", intensity="easy", distance=2300.0)]
    v2.heart["tok-maya"] += beats(run, bpm=154.3)
    sync(client)
    view = mine(client)
    from decimal import ROUND_HALF_UP, Decimal
    summed = sum(Decimal(w["v2"]["score"]["contribution"]) for w in view["workouts"])
    for w in view["workouts"]:
        score = w["v2"]["score"]
        assert abs(Decimal(score["base_points"]) + Decimal(score["adjusted_bonus"]) - Decimal(score["contribution"])) <= Decimal("0.01")
    rounded = int(summed.quantize(Decimal("1"), ROUND_HALF_UP))
    assert rounded == view["points"] == view["days"][0]["points"] == board(client)["maya"]["points"]


# ---------- the personal reference ----------


def test_without_enough_history_the_heart_factor_is_neutral_and_says_so(client, challenge, v2):
    link(client, "maya")
    history(v2, count=3)  # one short of the four needed
    run = wk("run", ago=300, minutes=40)
    v2.workouts["tok-maya"].append(run)
    v2.heart["tok-maya"].extend(beats(run, bpm=171.6))
    sync(client)
    heart = only(client)["v2"]["score"]["factors"]["heart"]
    assert (heart["value"], heart["state"], heart["reason"]) == ("1.00", "unavailable", "no_personal_reference")
    assert board(client)["maya"]["points"] == 40  # a high pulse alone earns nothing extra
    assert mine(client)["reference"] == {"frozen": True, "available": False, "workouts": 0}


def test_the_reference_is_frozen_and_ignores_workouts_inside_the_challenge(client, challenge, v2):
    user_id = link(client, "maya")
    history(v2)
    sync(client)
    with db.SessionLocal() as s:
        frozen = json.loads(s.scalar(select(db.Participant.hr_reference).where(db.Participant.user_id == user_id)))
    assert frozen == {"median": 140, "workouts": 5, "version": "proof-of-sweat-v2"}
    # A much harder block of training arrives later, some of it inside the challenge: the reference stays put.
    more = [wk(f"in{i}", ago=120 + 90 * i, minutes=30) for i in range(4)] + [wk("late-past", ago=3 * DAY + 200, minutes=30)]
    v2.workouts["tok-maya"].extend(more)
    v2.heart["tok-maya"].extend(s for w in more for s in beats(w, bpm=175.2))
    sync(client)
    with db.SessionLocal() as s:
        assert json.loads(s.scalar(select(db.Participant.hr_reference).where(db.Participant.user_id == user_id))) == frozen


def test_one_players_reference_never_reaches_another(client, challenge, v2):
    link(client, "maya"), link(client, "sam")
    history(v2, "maya")
    run = wk("sam-run", ago=300, minutes=40)
    v2.workouts["tok-sam"] = [run]
    v2.heart["tok-sam"] = beats(run, bpm=154.3)
    sync(client, "maya"), sync(client, "sam")
    assert only(client, "sam")["v2"]["score"]["factors"]["heart"]["reason"] == "no_personal_reference"


def test_cleanup_keeps_reference_workouts_until_the_reference_is_frozen(client, challenge, fakes, v2):
    link(client, "maya")
    # The challenge has not started yet in this test, so the reference cannot be frozen.
    with db.SessionLocal() as s:
        found = s.scalar(select(db.Challenge))
        found.start_time, found.end_time = NOW + timedelta(days=1), NOW + timedelta(days=8)
        s.commit()
    v2.workouts["tok-maya"] = [wk("ref", ago=10 * DAY, minutes=30), wk("ancient", ago=29 * DAY, minutes=30)]
    sync(client)
    with db.SessionLocal() as s:
        assert oura_sync.cleanup(s, now=NOW + timedelta(hours=1)) == 0  # both within 30 days of the start: kept
        assert oura_sync.cleanup(s, now=NOW + timedelta(days=1, hours=1)) == 0
        participant = s.scalar(select(db.Participant).where(db.Participant.hr_reference_at.is_(None)))
        participant.hr_reference_at = NOW  # frozen
        s.commit()
        assert oura_sync.cleanup(s, now=NOW + timedelta(hours=1)) == 2  # no longer needed: ordinary retention applies


# ---------- edits, old rows, both rule sets ----------


def test_an_intensity_edit_at_the_provider_changes_the_score(client, challenge, v2):
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk(minutes=50, activity="yoga", intensity="hard")]
    sync(client)
    assert board(client)["maya"]["points"] == 52  # 50 + 2.40 potential x 65% (Evidence 67) = 51.56
    v2.workouts["tok-maya"] = [wk(minutes=50, activity="yoga", intensity="easy")]
    assert sync(client).json()["updated"] == 1
    assert board(client)["maya"]["points"] == 49 and len(rows()) == 1  # 50 - 2.00 x 65% = 48.70


def test_missing_intensity_is_unavailable_not_assumed_moderate(client, challenge, v2):
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk(minutes=40, intensity=None)]
    sync(client)
    provider = only(client)["v2"]["score"]["factors"]["provider"]
    assert (provider["value"], provider["state"]) == ("1.00", "unavailable") and rows()[0].intensity is None


def test_workouts_imported_before_v2_are_checked_again_on_the_next_sync(client, challenge, v2):
    link(client, "maya")
    run = wk(minutes=40)
    v2.workouts["tok-maya"], v2.heart["tok-maya"] = [run], beats(run)
    sync(client)
    with db.SessionLocal() as s:  # as a row saved by the v1 importer looked
        row = s.scalar(select(db.ImportedActivity))
        row.content_hash, row.intensity, row.hr_usable, row.hr_median = "old-hash", None, None, None
        s.commit()
    sync(client)
    [row] = rows()
    assert row.intensity == "moderate" and row.hr_usable == 40 and row.status == "verified"


def test_v1_and_v2_challenges_score_the_same_workout_by_their_own_rules(client, v2, monkeypatch):
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat.TEMPLATE)
    old = client.post("/challenges", json={"address": CHALLENGE, "name": "v1", "mode": "public"}, headers=make_token("maya")).json()
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat2.TEMPLATE)
    new = client.post("/challenges", json={"address": OTHER, "name": "v2", "mode": "public"}, headers=make_token("maya")).json()
    assert (old["template"], new["template"]) == ("proof_of_sweat_v1", "proof_of_sweat_v2")
    assert (old["rules"]["generation"], new["rules"]["generation"]) == (1, 2)
    for address in (CHALLENGE, OTHER):
        client.post(f"/challenges/{address}/join", json={"consent": True}, headers=make_token("maya"))
    link(client, "maya")
    v2.workouts["tok-maya"] = [wk(minutes=45)]
    sync(client)
    assert mine(client)["points"] == 4 and mine(client, address=OTHER)["points"] == 45
    assert "v2" not in mine(client)["workouts"][0] or mine(client)["workouts"][0]["v2"] is None
    assert len(rows()) == 1


def test_each_rule_set_locks_its_own_fingerprint(client, monkeypatch):
    reply = client.post("/rules", json={"mode": "public", "length_seconds": 7 * 86400, "max_players": 8},
                        headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    locked = json.loads(reply.json()["ruleset"])["scoring"]
    assert locked == {"source": "fitness", "name": "proof_of_sweat_v2", "version": "proof-of-sweat-v2",
                      "sha256": sweat2.rules_fingerprint(), "stat_weights": None}
    rules.check_current({"scoring": locked})  # settles
    v1 = rules.scoring_rules("fitness", sweat.TEMPLATE)
    assert v1["sha256"] == sweat.rules_fingerprint() != locked["sha256"]
    rules.check_current({"scoring": v1})  # a challenge locked to v1 still settles on this server
    with pytest.raises(rules.RulesError):
        rules.check_current({"scoring": {**locked, "sha256": "0" * 64}})


def test_hand_entered_workouts_cannot_score_in_v2(client, challenge):
    reply = client.post("/me/activities", json={"type": "run", "minutes": 60, "points": 500, "multiplier": 1.25},
                        headers=make_token("maya"))
    assert reply.status_code == 200 and reply.json()["challenges"][0]["counted"] is False
    assert board(client)["maya"]["points"] == 0
    old = (NOW - timedelta(hours=3)).isoformat()
    assert client.post("/me/activities", json={"type": "run", "minutes": 60, "start": old}, headers=make_token("maya")).status_code == 400


def test_rejected_workouts_stay_rejected_whatever_their_index(client, challenge, v2):
    link(client, "maya")
    typed = wk(minutes=40, source="manual", distance=6000.0)
    v2.workouts["tok-maya"], v2.heart["tok-maya"] = [typed], beats(typed)
    sync(client)
    workout = only(client)
    assert workout["result"] == "rejected" and workout["points"] == 0.0 and workout["v2"]["evidence"]["label"] == "rejected"
    assert board(client)["maya"]["points"] == 0


# ---------- settlement and receipts ----------


def settle(client, fakes, world):
    link(client, "maya")
    history(world)
    run = wk("run", ago=300, minutes=40, intensity="hard", distance=7400.0)
    world.workouts["tok-maya"] += [run, wk("lift", ago=150, minutes=30, activity="strengthTraining"),
                                   wk("typed", ago=60, minutes=30, source="manual")]
    world.heart["tok-maya"] += beats(run, bpm=154.3)
    sync(client)
    end(fakes)
    reply = finish(client)
    assert reply.status_code == 200 and reply.json()["action"] == "settled", reply.text
    return client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()


def test_settlement_commits_v2_scores_and_receipts(client, challenge, fakes, v2):
    published = settle(client, fakes, v2)
    sheet = published["sheet"]
    assert sheet["rules"] == "proof_of_sweat_v2" and sheet["rules_version"] == "proof-of-sweat-v2"
    assert sheet["rules_sha256"] == sweat2.rules_fingerprint()
    assert sheet["scores"] == [{"wallet": WALLETS["maya"], "points": 70}, {"wallet": WALLETS["sam"], "points": 0}]
    # 40 min x 1.108 = 44.32, then 30 neutral minutes of which the day's last 10 are past the first hour: 20 + 6 = 26
    maya = sheet["proof_of_sweat"]["participants"][0]
    assert (maya["eligible_minutes"], maya["fitness_points"], len(maya["receipts"])) == (70, 70, 3)
    assert sheet["proof_of_sweat"]["schema"] == 2
    assert hashlib.sha256(published["canonical"].encode()).hexdigest() == published["sha256"]
    assert published["proof_problems"] == [] == attest.check_v2(published["proof"], challenge=CHALLENGE, sheet=sheet)
    changed = json.loads(json.dumps(sheet))
    changed["proof_of_sweat"]["participants"][0]["fitness_points"] = 99
    assert attest.check_v2(published["proof"], challenge=CHALLENGE, sheet=changed)


def test_owner_receipts_carry_the_breakdown_and_match_the_commitments(client, challenge, fakes, v2):
    published = settle(client, fakes, v2)
    committed = published["sheet"]["proof_of_sweat"]["participants"][0]["receipts"]
    view = mine(client)
    assert view["final"] is True and view["points"] == 70 and view["eligible_minutes"] == 70
    found = {}
    for item in view["receipts"]:
        assert hashlib.sha256(item["canonical"].encode()).hexdigest() == item["commitment"] and item["commitment"] in committed
        receipt = item["receipt"]
        assert receipt["schema"] == 2 and receipt["rules_version"] == "proof-of-sweat-v2"
        assert receipt["rules_sha256"] == sweat2.rules_fingerprint() and receipt["challenge"] == CHALLENGE
        found[receipt["result"], receipt["assurance"]] = receipt
    assert set(found) == {("verified", "strong"), ("verified", "limited"), ("rejected", None)}
    run = found["verified", "strong"]
    assert run["points"] == "44.32" and run["score"]["multiplier"] == "1.108" and run["evidence"]["index"] == 100
    assert (run["score"]["base_points"], run["score"]["potential_bonus"], run["score"]["reliability"],
            run["score"]["adjusted_bonus"]) == ("40.00", "4.32", "1.00", "4.32")
    # The receipts, the sheet and the leaderboard carry the same numbers: 44.32 + 26.00 rounds to the sheet's 70.
    assert published["sheet"]["scores"][0]["points"] == published["sheet"]["proof_of_sweat"]["participants"][0]["fitness_points"] == 70
    assert found["verified", "limited"]["points"] == "26.00" and found["verified", "limited"]["evidence"]["index"] == 67
    assert found["rejected", None]["evidence"]["label"] == "rejected"
    assert mine(client, "sam")["receipts"] == []


def test_nothing_private_is_in_the_v2_sheet_proof_or_receipts(client, challenge, fakes, fake_chain, v2, caplog):
    caplog.set_level(logging.DEBUG)
    published = settle(client, fakes, v2)
    public = json.dumps([published, [str(part) for part in fake_chain[-1]]])
    receipts = client.get(f"/me/sweat?challenge={CHALLENGE}", headers=make_token("maya")).text
    for private in ("oura-id", "154.3", "140.4", "bpm", "hr_median", "start_datetime", "tok-maya", "4321.5"):
        assert private not in public and private not in receipts and private not in caplog.text
    assert '"median"' not in public and '"median"' not in receipts  # not the reference, not a session's pulse
    for owner_only in ("7.4", "speed_kmh", "relative_percent", "strengthTraining"):
        assert owner_only not in public  # in the owner's receipt at most, never in the shared sheet


def test_settled_v2_scores_do_not_move(client, challenge, fakes, v2):
    settle(client, fakes, v2)
    v2.workouts["tok-maya"].append(wk("late", ago=20, minutes=60, intensity="hard"))
    sync(client)
    assert board(client)["maya"]["points"] == 70 and finish(client).json()["action"] == "none"


def test_deleting_fitness_data_clears_the_reference(client, challenge, v2):
    user_id = link(client, "maya")
    history(v2)
    sync(client)
    client.delete("/me/fitness", headers=make_token("maya"))
    with db.SessionLocal() as s:
        assert s.scalar(select(db.Participant.hr_reference).where(db.Participant.user_id == user_id)) is None
        assert not list(s.scalars(select(db.ImportedActivity)))
