""""What activities count?": the sport mapping, the locked ruleset entry, and enforcement end to end.

Oura and Solana are faked; every workout and heart-rate value is synthetic.
"""

import json

import pytest
from sqlalchemy import select

import activities
import attest
import config
import db
import rules
import sweat
import sweat3
from fitness import oura_sync
from test_rules import lock, preview
from test_stage4 import CHALLENGE, WALLETS, board, challenge, client, fakes, make_token  # noqa: F401
from test_stage6 import fake_chain  # noqa: F401
from test_sweat_flow import NOW, beats, end, finish, link, mine, rows, sweat_world, sync, wk  # noqa: F401
from test_sweat2_flow import history


@pytest.fixture(autouse=True)
def v3(monkeypatch, sweat_world):
    """New challenges use Proof of Sweat v3 (the production default)."""
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat3.TEMPLATE)
    return sweat_world


def create(client, sport, players=("maya", "sam")):
    """A recorded challenge that locked `sport`, joined by `players`."""
    reply = client.post("/challenges", json={"address": CHALLENGE, "name": "Sport week", "mode": "public",
                                             "activities": sport}, headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    for who in players:
        assert client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True},
                           headers=make_token(who)).status_code == 200
    return reply.json()


def by_activity(client, who="maya"):
    return {w["provider_activity"]: w for w in mine(client, who)["workouts"]}


# ---------- the mapping ----------


@pytest.mark.parametrize("name, sport", [
    ("running", "running"), ("Running", "running"), ("trailRunning", "running"), ("treadmill", "running"),
    ("walking", "walking"), ("nordic_walking", "walking"),
    ("hiking", "hiking"), ("trekking", "hiking"),
    ("cycling", "cycling"), ("indoorCycling", "cycling"), ("mountain biking", "cycling"), ("spinning", "cycling"),
    ("strengthTraining", "strength"), ("strength_training", "strength"), ("weightlifting", "strength"),
    ("functionalStrengthTraining", "strength"), ("calisthenics", "strength"),
    ("yoga", None), ("swimming", None), ("hiit", None), ("crossTraining", None), ("houseWork", None),
    ("sleeping", None), ("", None), (None, None), (42, None),
])
def test_oura_activity_names_map_to_one_sport_or_none(name, sport):
    assert activities.sport_of(name) == sport


def test_every_sport_name_is_a_supported_activity_and_belongs_to_one_sport():
    seen = set()
    for sport, names in activities.SPORTS.items():
        for name in names:
            assert oura_sync.category_of(name) is not None, name  # inside the curated list
            assert name == activities.normalize(name) and name not in seen
            seen.add(name)
    # The four distance sports are exactly the existing categories; strength is part of general workouts.
    for sport, category in (("running", "run"), ("walking", "walk"), ("hiking", "hike"), ("cycling", "ride")):
        assert set(activities.SPORTS[sport]) == set(oura_sync.ACTIVITY_MAP[category])
    assert set(activities.SPORTS["strength"]) < set(oura_sync.ACTIVITY_MAP["workout"])
    assert activities.CHOICES == ("all", "running", "walking", "hiking", "cycling", "strength")


# ---------- locked in the ruleset ----------


def test_all_exercise_leaves_the_ruleset_exactly_as_it_was(client, fakes):
    default = preview(client, mode="public")
    assert preview(client, mode="public", activities="all") == default
    assert "activities" not in json.loads(default["ruleset"])


def test_one_sport_is_written_into_the_ruleset_and_changes_its_hash(client, fakes):
    default, running, cycling = (preview(client, mode="public", activities=a) for a in ("all", "running", "cycling"))
    assert len({default["rules_hash"], running["rules_hash"], cycling["rules_hash"]}) == 3
    locked = json.loads(running["ruleset"])["activities"]
    assert locked == {"selection": "running", "label": "Running", "version": "activities-v1", "provider": "oura",
                      "oura_activities": sorted(activities.SPORTS["running"])}
    # The scoring rules themselves are untouched: same name, version and fingerprint.
    assert json.loads(running["ruleset"])["scoring"] == json.loads(default["ruleset"])["scoring"]


def test_unknown_choices_and_rules_without_oura_are_refused(client, fakes, monkeypatch):
    assert client.post("/rules", json={"length_seconds": 86400, "activities": "chess"}).status_code == 422
    stats = client.post("/rules", json={"length_seconds": 86400, "mode": "league", "scoring_source": "league_stats",
                                        "activities": "running"})
    assert stats.status_code == 400 and "Proof of Sweat" in stats.json()["detail"]
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat.LEGACY_TEMPLATE)
    assert client.post("/rules", json={"length_seconds": 86400, "activities": "running"}).status_code == 400
    assert client.post("/rules", json={"length_seconds": 86400, "activities": "all"}).status_code == 200


def test_the_sport_recorded_must_be_the_sport_locked_onchain(client, fakes):
    lock(fakes, preview(client, mode="public", activities="running"))
    for other in ("all", "cycling"):
        reply = client.post("/challenges", json={"address": CHALLENGE, "name": "x", "mode": "public",
                                                 "activities": other}, headers=make_token("maya"))
        assert reply.status_code == 400 and "not the rules you chose" in reply.json()["detail"]
    made = create(client, "running", players=())
    assert made["activities"] == {"selection": "running", "label": "Running", "restricted": True}
    assert json.loads(made["ruleset"])["activities"]["selection"] == "running"


def test_existing_and_general_challenges_report_all_exercise(client, challenge):
    reply = client.get(f"/challenges/{CHALLENGE}/state", headers=make_token("maya")).json()
    assert reply["challenge"]["activities"] == {"selection": "all", "label": "All exercise", "restricted": False}


# ---------- enforcement ----------


def test_only_the_matching_sport_scores_in_a_sport_challenge(client, fakes, v3):
    create(client, "running")
    link(client, "maya")
    v3.workouts["tok-maya"] = [wk("run", ago=500, minutes=40), wk("ride", ago=400, minutes=40, activity="cycling"),
                               wk("lift", ago=300, minutes=40, activity="strengthTraining"),
                               wk("walk", ago=200, minutes=40, activity="walking")]
    sync(client)
    assert board(client)["maya"]["points"] == 40
    found = by_activity(client)
    assert (found["running"]["result"], found["running"]["points"]) == ("verified", 40.0)
    for name in ("cycling", "strengthTraining", "walking"):
        workout = found[name]
        assert (workout["result"], workout["reason"], workout["points"]) == ("rejected", "activity_not_in_challenge", 0.0)
        checks = {c["code"]: (c["result"], c["reason"]) for c in workout["checks"]}
        assert checks["activity"] == ("failed", "activity_not_in_challenge") and checks["scoring"][0] == "failed"
        assert checks["provenance"][0] == "passed"  # the record itself is fine; it is just another sport
        assert workout["v2"]["evidence"]["label"] == "rejected" and workout["v2"]["score"]["contribution"] == "0"
    assert mine(client)["eligible_minutes"] == 40
    # The stored workout is untouched: the same record still counts in a general challenge.
    assert {r.provider_activity: r.status for r in rows()} == {
        "running": "verified", "cycling": "verified", "strengthTraining": "verified", "walking": "verified"}


@pytest.mark.parametrize("sport, counted", [
    ("walking", "walking"), ("hiking", "hiking"), ("cycling", "cycling"), ("strength", "strengthTraining"),
])
def test_each_sport_counts_its_own_activities_only(client, fakes, v3, sport, counted):
    create(client, sport)
    link(client, "maya")
    names = ["running", "walking", "hiking", "cycling", "strengthTraining", "yoga"]
    v3.workouts["tok-maya"] = [wk(f"w{i}", ago=600 - 60 * i, minutes=30, activity=name) for i, name in enumerate(names)]
    sync(client)
    assert {name: w["result"] for name, w in by_activity(client).items()} == {
        name: "verified" if name == counted else "rejected" for name in names}
    assert board(client)["maya"]["points"] == 30


def test_a_general_challenge_counts_every_supported_activity_and_nothing_else(client, challenge, v3):
    link(client, "maya")
    names = ["running", "cycling", "strengthTraining", "yoga", "sleeping", "houseWork"]
    v3.workouts["tok-maya"] = [wk(f"w{i}", ago=1300 - 60 * i, minutes=10, activity=name) for i, name in enumerate(names)]
    sync(client)
    found = by_activity(client)
    assert {name: w["result"] for name, w in found.items()} == {
        "running": "verified", "cycling": "verified", "strengthTraining": "verified", "yoga": "verified",
        "sleeping": "rejected", "houseWork": "rejected"}
    assert found["sleeping"]["reason"] == "unsupported_activity"
    assert board(client)["maya"]["points"] == 40


def test_another_sport_never_uses_up_time_the_right_sport_could_score(client, fakes, v3):
    create(client, "running")
    link(client, "maya")
    # A long bike ride that starts first and covers the run entirely: in a general challenge the run would
    # be a duplicate. Here the ride does not count, so the run is credited in full.
    v3.workouts["tok-maya"] = [wk("ride", ago=600, minutes=120, activity="cycling"), wk("run", ago=560, minutes=30)]
    sync(client)
    found = by_activity(client)
    assert (found["running"]["result"], found["running"]["eligible_minutes"]) == ("verified", 30)
    assert board(client)["maya"]["points"] == 30


def test_a_matching_sport_must_still_pass_every_mandatory_check(client, fakes, v3):
    create(client, "running")
    link(client, "maya")
    v3.workouts["tok-maya"] = [
        wk("rocket", ago=700, minutes=30, distance=30000.0),  # 60 km/h "run"
        wk("typed", ago=600, minutes=30, source="manual"),
        wk("short", ago=500, minutes=5),
        wk("twin", ago=400, minutes=30), wk("twin2", ago=400, minutes=30),  # the same half hour twice
    ]
    sync(client)
    results = sorted((w["result"], w["reason"]) for w in mine(client)["workouts"])
    assert results == [("rejected", "duplicate_time"), ("rejected", "manual_entry"), ("rejected", "too_fast"),
                       ("rejected", "under_minimum"), ("verified", "no_heart_rate")]
    rocket = next(w for w in mine(client)["workouts"] if w["reason"] == "too_fast")
    checks = {c["code"]: c["result"] for c in rocket["checks"]}
    assert checks["plausibility"] == "failed" and checks["activity"] == "passed"  # a mandatory check, not a lower score
    assert rocket["points"] == 0.0 and board(client)["maya"]["points"] == 30


def test_strength_training_is_not_penalized_for_having_no_distance(client, fakes, v3):
    create(client, "strength")
    link(client, "maya")
    history(v3, bpm=140.0)
    lift = wk("lift", ago=300, minutes=40, activity="strengthTraining")  # no distance at all
    v3.workouts["tok-maya"].append(lift)
    v3.heart["tok-maya"].extend(beats(lift, bpm=140.0))
    sync(client)
    workout = by_activity(client)["strengthTraining"]
    checks = {c["code"]: (c["result"], c["reason"]) for c in workout["checks"]}
    assert checks["plausibility"] == ("passed", "no_distance")
    score, evidence = workout["v2"]["score"], workout["v2"]["evidence"]
    assert score["factors"]["movement"] == {"value": "1.00", "state": "unavailable", "reason": "no_pace_for_category",
                                            "bonus": "0.00"}
    # Full base points, the whole effort adjustment counts, and the evidence is rated strong.
    assert (workout["result"], workout["assurance"], workout["points"]) == ("verified", "strong", 40.0)
    assert evidence["index"] == 92 and score["reliability"] == "1.00"


def test_missing_heart_rate_keeps_a_matching_workout_eligible(client, fakes, v3):
    create(client, "cycling")
    link(client, "maya")
    v3.workouts["tok-maya"] = [wk(minutes=40, activity="cycling", distance=14000.0)]
    sync(client)
    workout = by_activity(client)["cycling"]
    assert (workout["result"], workout["assurance"]) == ("verified", "limited")
    assert workout["v2"]["evidence"]["limits"] == ["no_heart_rate"] and workout["v2"]["score"]["base_points"] == "40.00"


def test_syncing_again_changes_nothing_in_a_sport_challenge(client, fakes, v3):
    create(client, "running")
    link(client, "maya")
    v3.workouts["tok-maya"] = [wk("run", ago=300, minutes=40), wk("ride", ago=200, minutes=40, activity="cycling")]
    sync(client)
    before = mine(client)
    for _ in range(3):
        assert sync(client).status_code == 200
    after = mine(client)
    assert after["workouts"] == before["workouts"] and after["points"] == before["points"] == 40 and len(rows()) == 2


def test_a_workout_still_being_checked_shows_as_another_sport_at_once(client, fakes, v3):
    create(client, "running")
    link(client, "maya")
    v3.workouts["tok-maya"] = [wk("ride", ago=200, minutes=40, activity="cycling")]
    sync(client)
    with db.SessionLocal() as s:  # as if its heart rate could not be read yet
        row = s.scalar(select(db.ImportedActivity))
        row.status, row.assurance, row.checks = "pending", None, None
        s.commit()
    assert rows()[0].status == "pending"
    workout = by_activity(client)["cycling"]
    assert (workout["result"], workout["reason"]) == ("rejected", "activity_not_in_challenge")
    assert workout["v2"]["evidence"]["label"] == "rejected"


def test_one_workout_counts_by_each_challenges_own_locked_list(client, fakes, v3):
    """The restriction is read from the challenge's ruleset, not from today's mapping."""
    create(client, "running")
    link(client, "maya")
    v3.workouts["tok-maya"] = [wk("run", ago=300, minutes=40)]
    sync(client)
    assert board(client)["maya"]["points"] == 40
    original = dict(activities.SPORTS)
    try:
        activities.SPORTS["running"] = ("somethingelse",)  # a later edit to the mapping
        client.post("/integrations/oura/sync", headers=make_token("maya"))
        assert board(client)["maya"]["points"] == 40  # the challenge keeps the list it locked
    finally:
        activities.SPORTS.update(original)


# ---------- settlement ----------


def test_a_sport_challenge_settles_on_matching_workouts_only(client, fakes, v3):
    create(client, "running")
    link(client, "maya")
    link(client, "sam")
    v3.workouts["tok-maya"] = [wk("run", ago=300, minutes=30)]
    v3.workouts["tok-sam"] = [wk("ride", ago=400, minutes=120, activity="cycling", distance=40000.0),
                              wk("lift", ago=200, minutes=60, activity="strengthTraining")]
    sync(client)
    sync(client, "sam")
    assert board(client)["sam"]["points"] == 0
    end(fakes)
    reply = finish(client)
    assert reply.status_code == 200 and reply.json()["action"] == "settled", reply.text
    assert reply.json()["winners"] == [WALLETS["maya"]]  # three hours of cycling and lifting win nothing here
    published = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()
    sheet = published["sheet"]
    assert sheet["scores"] == [{"wallet": WALLETS["maya"], "points": 30}, {"wallet": WALLETS["sam"], "points": 0}]
    assert published["proof_problems"] == [] == attest.check_v2(published["proof"], challenge=CHALLENGE, sheet=sheet)
    maya, sam = sheet["proof_of_sweat"]["participants"]
    assert (maya["eligible_minutes"], len(maya["receipts"])) == (30, 1)
    assert (sam["eligible_minutes"], sam["fitness_points"], len(sam["receipts"])) == (0, 0, 2)
    receipts = mine(client, "sam")["receipts"]
    assert sorted(r["commitment"] for r in receipts) == sam["receipts"]
    for saved in receipts:
        receipt = saved["receipt"]
        assert attest.sheet_sha256(receipt).hex() == saved["commitment"]
        assert (receipt["result"], receipt["reason"], receipt["points"]) == ("rejected", "activity_not_in_challenge", "0.00")
        assert receipt["activities_counted"] == "running"
        assert {"code": "activity", "result": "failed", "reason": "activity_not_in_challenge"} in receipt["checks"]


def test_general_challenge_receipts_are_unchanged(client, challenge, fakes, v3):
    link(client, "maya")
    v3.workouts["tok-maya"] = [wk("run", ago=300, minutes=30)]
    sync(client)
    end(fakes)
    assert finish(client).json()["action"] == "settled"
    [saved] = mine(client)["receipts"]
    assert "activities_counted" not in saved["receipt"] and saved["receipt"]["result"] == "verified"
