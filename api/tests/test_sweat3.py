"""Proof of Sweat v3: v2's verification with consequential effort (api/sweat3.py), the files the
website's sample receipt is checked against, and v2/v3 challenges living side by side.
Every workout and heart-rate value is synthetic."""

import json
from decimal import Decimal as D

import pytest

import config
import rules
import scores
import sweat
import sweat2
import sweat3
import sweat_sample
from test_stage4 import CHALLENGE, WALLETS, board, challenge, client, fakes, make_token, state  # noqa: F401
from test_stage6 import fake_chain  # noqa: F401
from test_sweat2_flow import history, only
from test_sweat_flow import OTHER, beats, end, finish, link, mine, sweat_world, sync, wk  # noqa: F401


def heart(pct, minutes=40, covered=None):
    covered = minutes if covered is None else covered
    return sweat3.HeartSummary(minutes, covered, covered, 4, True, False, covered, 100 + pct)


REF = {"median": 100, "workouts": 6}


# ---------- rules identity ----------


def test_v3_is_its_own_rule_set_and_the_earlier_ones_did_not_move():
    assert (sweat3.RULES_VERSION, sweat3.TEMPLATE) == ("proof-of-sweat-v3", "proof_of_sweat_v3")
    # Locked onchain by existing challenges: these two must never change.
    assert sweat.rules_fingerprint() == "43143b257a0d5e734c25378000ce858aaeb9d53918d12cbfdb469674672ab180"
    assert sweat2.rules_fingerprint() == "b9bd8375b87d6c704a54dc0fbd48121f31595c344ce853935b63eb7708c661a6"
    # Locked by every v3 challenge: changing a constant must come with a new RULES_VERSION and this value.
    assert sweat3.rules_fingerprint() == "3d0021d727de45dc86e9df82dc4e4092efcaf1a54e915cc757ae5b3684b261c9"
    assert sweat3.rules()["gates"] == sweat.rules()
    # Verification is v2's, object for object: only the effort numbers differ.
    for shared in ("evidence_index", "reliability", "bands", "strong_evidence", "unavailable_signal", "final", "rounding"):
        assert sweat3.rules()[shared] == sweat2.rules()[shared]
    assert sweat3.evidence_index is sweat2.evidence_index and sweat3.score is sweat2.score


def test_weights_and_range():
    assert sweat3.WEIGHTS == {"heart": D("0.45"), "movement": D("0.30"), "provider": D("0.25")}
    assert sum(sweat3.WEIGHTS.values()) == 1
    assert sweat3.MULTIPLIER_RANGE == (D("0.85"), D("1.50"))


# ---------- effort ----------


def multiplier(intensity, pct, category, km, minutes=40, hr=True, reference=REF):
    return sweat3.effort_multiplier(
        sweat3.provider_factor(intensity),
        sweat3.heart_factor(heart(pct, minutes) if hr else None, reference),
        sweat3.movement_factor(category, km, minutes))


def test_a_hard_session_clearly_outscores_an_easy_one_of_the_same_length():
    hard = multiplier("hard", 10, "run", 7.4)  # 0.25*1.30 + 0.45*1.30 + 0.30*1.20
    easy = multiplier("easy", -8, "run", 4.6)  # 0.2125 + 0.36 + 0.27 = 0.8425, held at the floor
    assert (hard, easy) == (D("1.270"), D("0.850"))
    assert 40 * hard - 40 * easy > 16  # v2 separated these two by about 7 points


def test_the_signals_can_reach_the_cap_but_not_pass_it():
    assert multiplier("hard", 22, "run", 9.0) == D("1.500")  # 0.325 + 0.7425 + 0.435 = 1.5025
    assert multiplier("hard", 60, "run", 14.0) == D("1.500")
    assert multiplier("easy", -30, "run", 3.0) == D("0.850")
    assert sweat3.heart_factor(heart(60), REF).value == D("1.650") and sweat3.heart_factor(heart(-30), REF).value == D("0.800")


def test_heart_rate_is_linear_and_monotonic_in_between():
    values = [sweat3.heart_factor(heart(p), REF).value for p in range(-8, 23)]
    assert values == sorted(values) and len(set(values)) > 25
    assert sweat3.heart_factor(heart(10), REF).value == D("1.300") and sweat3.heart_factor(heart(0), REF).value == D("1.000")


def test_missing_signals_are_exactly_neutral_and_never_an_advantage():
    assert multiplier(None, 0, "workout", None, hr=False) == D("1.000")
    assert sweat3.heart_factor(None, REF).value == D("1.00")
    assert sweat3.heart_factor(heart(15), None).reason == "no_personal_reference"
    assert sweat3.heart_factor(heart(15, covered=15), REF).reason == "not_enough_heart_rate"  # under half the minutes
    # Losing a signal that was helping lowers the multiplier; nothing is redistributed to the others.
    assert multiplier("hard", 10, "run", 7.4, hr=False) < multiplier("hard", 10, "run", 7.4)
    # Without any heart rate the most the other two can do is well short of the cap.
    assert multiplier("hard", 0, "run", 9.0, hr=False) == D("1.210")


def test_walking_tops_out_below_running():
    assert sweat3.movement_factor("walk", 5.0, 40).value == D("1.30") < sweat3.movement_factor("run", 9.0, 40).value
    assert sweat3.movement_factor("workout", 5.0, 40).state == sweat3.UNAVAILABLE


def test_weak_evidence_still_holds_back_the_bonus_and_never_the_base():
    strong = sweat_sample.sample("run", 40, "hard", 10, 7.33, 40, 4)
    weak = sweat_sample.sample("workout", 40, "hard", None, None, 0, 0)
    assert (strong["evidence"]["index"], strong["score"]["contribution"]) == (100, "50.80")
    assert (weak["evidence"]["index"], weak["score"]["reliability"]) == (67, "0.65")
    assert (weak["score"]["base_points"], weak["score"]["potential_bonus"], weak["score"]["adjusted_bonus"]) == ("40.00", "3.00", "1.95")


def test_diminishing_returns_still_apply():
    long = sweat_sample.sample("run", 150, "hard", 10, 27.5, 150, 4)
    assert long["score"]["base_points"] == "103.50" and long["score"]["band_minutes"] == [60.0, 60.0, 30.0, 0.0]


# ---------- the website's sample receipt uses these exact rules ----------


def test_the_committed_rules_and_examples_for_the_website_are_current():
    """If this fails, a scoring number changed: run `python sweat_sample.py write` in api/ and
    `npm run check:sweat` in web/, and commit both files."""
    assert sweat_sample.RULES_FILE.read_text() == sweat_sample.rules_text()
    assert sweat_sample.VECTORS_FILE.read_text() == sweat_sample.vectors_text()
    assert json.loads(sweat_sample.RULES_FILE.read_text())["sha256"] == sweat3.rules_fingerprint()


# ---------- challenges ----------


@pytest.fixture(autouse=True)
def v3(monkeypatch, sweat_world):
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat3.TEMPLATE)
    return sweat_world


def test_v3_is_what_new_challenges_get_by_default():
    import importlib
    import os
    saved = os.environ.pop("NEW_CHALLENGE_RULES")
    try:
        assert importlib.reload(config).NEW_CHALLENGE_RULES == "proof_of_sweat_v3"
    finally:
        os.environ["NEW_CHALLENGE_RULES"] = saved
        importlib.reload(config)


def test_a_v3_challenge_scores_and_settles_under_v3(client, challenge, fakes, v3):
    link(client, "maya")
    history(v3)
    run = wk("run", ago=300, minutes=40, intensity="hard", distance=7400.0)
    v3.workouts["tok-maya"] += [run, wk("lift", ago=150, minutes=30, activity="strengthTraining")]
    v3.heart["tok-maya"] += beats(run, bpm=154.3)  # 10% above the reference of 140
    sync(client)
    view = mine(client)
    assert (view["rules"]["version"], view["rules"]["generation"]) == ("proof-of-sweat-v3", 3)
    hard = next(w for w in view["workouts"] if w["v2"]["intensity"] == "hard")
    score = hard["v2"]["score"]
    assert score["weights"] == {"heart": "0.45", "movement": "0.30", "provider": "0.25"}
    assert (score["multiplier"], score["multiplier_range"], score["contribution"]) == ("1.270", ["0.85", "1.50"], "50.80")
    assert board(client)["maya"]["points"] == 77  # 50.80 + 30 neutral minutes, 10 of them in the day's second hour
    end(fakes)
    reply = finish(client)
    assert reply.status_code == 200 and reply.json()["action"] == "settled", reply.text
    sheet = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()["sheet"]
    assert (sheet["rules"], sheet["rules_version"], sheet["rules_sha256"]) == (
        "proof_of_sweat_v3", "proof-of-sweat-v3", sweat3.rules_fingerprint())
    assert sheet["scores"][0] == {"wallet": WALLETS["maya"], "points": 77}


def test_v2_and_v3_challenges_score_the_same_workout_by_their_own_rules(client, sweat_world, monkeypatch):
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat2.TEMPLATE)
    old = client.post("/challenges", json={"address": CHALLENGE, "name": "v2", "mode": "public"}, headers=make_token("maya")).json()
    monkeypatch.setattr(config, "NEW_CHALLENGE_RULES", sweat3.TEMPLATE)
    new = client.post("/challenges", json={"address": OTHER, "name": "v3", "mode": "public"}, headers=make_token("maya")).json()
    assert (old["template"], new["template"]) == ("proof_of_sweat_v2", "proof_of_sweat_v3")
    assert (old["rules"]["generation"], new["rules"]["generation"]) == (2, 3)
    for address in (CHALLENGE, OTHER):
        client.post(f"/challenges/{address}/join", json={"consent": True}, headers=make_token("maya"))
    link(client, "maya")
    history(sweat_world)
    run = wk("run", ago=300, minutes=40, intensity="hard", distance=7400.0)
    sweat_world.workouts["tok-maya"] += [run]
    sweat_world.heart["tok-maya"] += beats(run, bpm=154.3)
    sync(client)
    assert only(client)["v2"]["score"]["contribution"] == "44.32"  # the v2 challenge is untouched by v3
    assert only(client, address=OTHER)["v2"]["score"]["contribution"] == "50.80"


def test_each_version_still_settles_only_under_its_own_fingerprint(v3):
    for engine in (sweat, sweat2, sweat3):
        locked = rules.scoring_rules("fitness", engine.TEMPLATE)
        assert (locked["version"], locked["sha256"]) == (engine.RULES_VERSION, engine.rules_fingerprint())
        rules.check_current({"scoring": locked})
        with pytest.raises(rules.RulesError):
            rules.check_current({"scoring": {**locked, "sha256": "0" * 64}})
    assert rules.workouts_policy(rules.scoring_rules("fitness"))["count"] == ["verified"]
    assert scores.GENERATION[rules.fitness_template()] == 3
