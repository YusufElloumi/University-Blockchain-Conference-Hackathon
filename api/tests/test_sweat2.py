"""Proof of Sweat v2 math (api/sweat2.py): effective minutes, effort factors, Evidence Index. Synthetic data only."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest

import sweat
import sweat2

START = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
END = START + timedelta(days=7)


def wk(ref="a", minutes=30, at=60, type="run", km=None):
    begin = START + timedelta(minutes=at)
    return sweat.Workout(ref, "oura", type, "confirmed", begin, begin + timedelta(minutes=minutes), km)


def item(ref="a", minutes=30, at=60, multiplier="1.000", **kw):
    return sweat2.Item(wk(ref, minutes, at, **kw), sweat.VERIFIED, None, D(multiplier))


def total(*items):
    return sweat2.score(list(items), START, END)


def hr(second, bpm=140, source="workout", begin=START + timedelta(minutes=60)):
    return {"timestamp": (begin + timedelta(seconds=second)).isoformat(), "bpm": bpm, "source": source}


def summary(samples, minutes=30):
    w = wk(minutes=minutes)
    return sweat2.heart_summary(samples, w.start, w.end)


# ---------- effective minutes ----------


@pytest.mark.parametrize("minutes, effective", [(0, "0"), (10, "10"), (30, "30"), (60, "60"), (61, "60.6"), (90, "78"),
                                                (120, "96"), (121, "96.25"), (150, "103.5"), (180, "111"), (240, "111")])
def test_effective_minutes_taper_and_stop_at_three_hours(minutes, effective):
    assert sweat2.effective_minutes(minutes) == D(effective)


@pytest.mark.parametrize("minutes, points", [(9, 0), (10, 10), (40, 40), (60, 60), (90, 78), (120, 96), (180, 111), (300, 111)])
def test_a_neutral_workout_scores_its_effective_minutes(minutes, points):
    assert total(item(minutes=minutes)).total == points


def test_two_workouts_share_the_days_bands_in_time_order():
    sheet = total(item("a", 45, at=60), item("b", 45, at=300))
    assert sheet.total == 78  # 45 + 15 full, then 30 x 0.6: not 90
    assert (sheet.lines["a"].contribution, sheet.lines["b"].contribution) == (D(45), D(33))
    assert sheet.lines["b"].bands == [15 * 60, 30 * 60, 0, 0]
    assert total(item("b", 45, at=300), item("a", 45, at=60)).lines["b"].contribution == D(33)  # order of arrival is irrelevant


def test_the_multiplier_applies_to_each_workouts_own_share():
    sheet = total(item("a", 60, at=60, multiplier="1.100"), item("b", 60, at=300, multiplier="0.900"))
    assert sheet.lines["a"].contribution == D("66.000") and sheet.lines["b"].contribution == D("32.400")
    assert sheet.total == 98  # 98.4 rounds down


def test_only_the_daily_total_is_rounded_half_up():
    # 15 minutes x 1.03 = 15.45 each: 30.9 for the day -> 31, not 15 + 15.
    sheet = total(item("a", 15, at=60, multiplier="1.030"), item("b", 15, at=300, multiplier="1.030"))
    assert sheet.days[0].contribution == D("30.90") and sheet.total == 31
    assert sheet.lines["a"].points == D("15.45")
    half = total(item("a", 10, multiplier="1.050"))  # 10.5 -> 11
    assert half.total == 11


def test_each_challenge_day_has_its_own_bands():
    sheet = total(item("a", 90, at=60), item("b", 90, at=24 * 60 + 60))
    assert {d: day.points for d, day in sheet.days.items()} == {0: 78, 1: 78}


def test_a_workout_across_a_day_boundary_is_split_between_the_days():
    sheet = total(item("a", 100, at=24 * 60 - 70))  # 70 minutes in day 0, 30 in day 1
    assert sheet.days[0].contribution == D(66) and sheet.days[1].contribution == D(30)
    assert sheet.lines["a"].days == {0: 4200, 1: 1800} and sheet.total == 96


def test_overlap_is_counted_once_before_the_bands():
    sheet = total(item("a", 30, at=60), item("b", 30, at=75))  # 45 unique minutes
    assert sheet.total == 45 and sheet.eligible_minutes == 45 and sheet.lines["b"].overlap == sweat.LIMITED
    assert total(item("a", 40, at=60), item("b", 20, at=70)).lines["b"].reason == "duplicate_time"


def test_only_time_inside_the_challenge_counts():
    assert total(item("a", 40, at=-25)).total == 15
    assert total(item("a", 40, at=-33)).lines["a"].reason == "under_minimum_in_window"
    assert total(item("a", 40, at=-60)).lines == {}
    assert total(item("a", 40, at=7 * 24 * 60 - 12)).total == 12


def test_rejected_and_pending_workouts_score_nothing():
    items = [sweat2.Item(wk("a"), sweat.REJECTED, "manual_entry"), sweat2.Item(wk("b", at=200), sweat.PENDING)]
    sheet = sweat2.score(items, START, END)
    assert sheet.total == 0 and sheet.rejected == {"a": "manual_entry"} and sheet.lines["b"].status == sweat.PENDING


def test_ten_minutes_makes_a_day_active():
    assert total(item(minutes=10)).days[0].active and not total(item("a", 12, at=-3)).days


# ---------- effort factors ----------


@pytest.mark.parametrize("intensity, value, state", [("easy", "0.90", "provider_estimated"), ("moderate", "1.00", "provider_estimated"),
                                                     ("hard", "1.12", "provider_estimated"), (None, "1.00", "unavailable"),
                                                     ("extreme", "1.00", "unavailable")])
def test_provider_factor(intensity, value, state):
    factor = sweat2.provider_factor(intensity)
    assert (factor.value, factor.state) == (D(value), state)


def dense(bpm=150, minutes=30, source="workout"):
    return [hr(60 * m + s, bpm, source) for m in range(minutes) for s in (5, 35)]


REFERENCE = {"median": 140, "workouts": 6}


@pytest.mark.parametrize("bpm, value", [(140, "1.000"), (151, "1.098"), (154, "1.125"), (160, "1.150"), (190, "1.150"),
                                        (133, "0.938"), (126, "0.900"), (95, "0.900")])
def test_heart_factor_is_relative_to_the_players_own_reference_and_capped(bpm, value):
    factor = sweat2.heart_factor(summary(dense(bpm)), REFERENCE)
    assert factor.value == D(value) and factor.state == "measured"
    assert "bpm" not in str(factor.detail) and str(bpm) not in str(factor.detail)  # only a relative percentage


def test_heart_factor_is_monotonic():
    values = [sweat2.heart_factor(summary(dense(bpm)), REFERENCE).value for bpm in range(90, 200, 3)]
    assert values == sorted(values)


def test_the_same_heart_rate_means_different_things_for_different_people():
    session = summary(dense(150))
    assert sweat2.heart_factor(session, {"median": 135}).value > 1 > sweat2.heart_factor(session, {"median": 165}).value


@pytest.mark.parametrize("samples, reference, reason", [
    ([], REFERENCE, "no_heart_rate"),
    (dense(150, minutes=9), REFERENCE, "not_enough_heart_rate"),  # 9 of 30 minutes
    (dense(150, source="awake"), REFERENCE, "not_enough_heart_rate"),  # background readings only
    ([hr(10, 185)], REFERENCE, "not_enough_heart_rate"),  # one high reading proves nothing
    (dense(150), None, "no_personal_reference"),
])
def test_heart_factor_is_neutral_without_enough_to_go_on(samples, reference, reason):
    factor = sweat2.heart_factor(summary(samples), reference)
    assert (factor.value, factor.state, factor.reason) == (D("1.00"), "unavailable", reason)


def test_heart_summary_groups_by_minute_and_ignores_bad_samples():
    burst = [hr(s, 200) for s in range(0, 50)] + [hr(60 * m + 5, 140) for m in range(1, 20)]
    found = summary(burst)
    assert found.median == 140 and found.bins_covered == 20 and found.usable == 69  # the burst is one minute, not 50 votes
    junk = [hr(30, 400), hr(90, 5), hr(150, None), hr(210, True), "x", {"bpm": 150}, {"timestamp": "no", "bpm": 150}]
    found = summary(junk + dense(150))
    assert found.warning and found.median == 150
    assert summary([hr(-30), hr(30 * 60)]).bins_covered == 0  # outside the workout


def test_heart_summary_quarters():
    assert summary([hr(60 * m) for m in range(7)]).quarters == 1  # all inside the first 7.5 minutes of 30
    assert summary([hr(60 * m) for m in range(16)]).quarters == 3
    assert summary(dense()).quarters == 4


def test_personal_reference_needs_enough_recent_workouts():
    assert sweat2.personal_reference([150, 140, 145]) is None
    assert sweat2.personal_reference([150, 140, 145, 135]) == {"median": 142, "workouts": 4, "version": "proof-of-sweat-v2"}
    many = sweat2.personal_reference([100] * 10 + [200] * 20)
    assert many == {"median": 100, "workouts": 10, "version": "proof-of-sweat-v2"}  # only the 10 most recent
    assert sweat2.personal_reference([150, None, 0, 140, 145]) is None


@pytest.mark.parametrize("category, km, minutes, value", [
    ("run", 3.5, 30, "0.95"), ("run", 4.5, 30, "1.00"), ("run", 5.5, 30, "1.05"), ("run", 6.2, 30, "1.10"),
    ("walk", 1.5, 30, "0.95"), ("walk", 2.4, 30, "1.00"), ("walk", 3.0, 30, "1.05"), ("walk", 3.4, 30, "1.10"),
    ("hike", 1.0, 30, "0.97"), ("hike", 2.0, 30, "1.00"), ("hike", 3.0, 30, "1.05"),
    ("ride", 6, 30, "0.95"), ("ride", 10, 30, "1.00"), ("ride", 12, 30, "1.05"), ("ride", 15, 30, "1.10"),
    ("swim", 0.5, 30, "0.95"), ("swim", 1.0, 30, "1.00"), ("swim", 1.4, 30, "1.05"), ("swim", 1.7, 30, "1.10"),
])
def test_movement_bands_are_per_sport(category, km, minutes, value):
    factor = sweat2.movement_factor(category, km, minutes)
    assert (factor.value, factor.state) == (D(value), "measured")


@pytest.mark.parametrize("category, km, reason", [("workout", 5, "no_pace_for_category"), ("run", None, "no_distance"),
                                                  ("run", 0, "no_distance"), (None, 5, "no_pace_for_category")])
def test_movement_is_neutral_when_it_says_nothing(category, km, reason):
    factor = sweat2.movement_factor(category, km, 30)
    assert (factor.value, factor.state, factor.reason) == (D("1.00"), "unavailable", reason)


def test_walking_pace_that_is_brisk_is_not_a_fast_run():
    assert sweat2.movement_factor("walk", 3.4, 30).value > sweat2.movement_factor("run", 3.4, 30).value


def F(value, state="measured"):
    return sweat2.Factor(D(value), state)


def test_the_weighted_combination_and_its_limits():
    assert sweat2.effort_multiplier(F("1.12"), F("1.12"), F("1.08")) == D("1.112")  # the spec's worked example
    assert sweat2.effort_multiplier(F("1.00"), F("1.00"), F("1.00")) == D("1.000")
    assert sweat2.effort_multiplier(F("1.12"), F("1.15"), F("1.10")) == D("1.128")  # the most the real factors allow
    assert sweat2.effort_multiplier(F("0.90"), F("0.90"), F("0.95")) == D("0.910")
    assert sweat2.effort_multiplier(F("2"), F("2"), F("2")) == D("1.250") and sweat2.effort_multiplier(F("0"), F("0"), F("0")) == D("0.850")


def test_missing_signals_are_neutral_and_never_renormalized():
    hard_only = sweat2.effort_multiplier(sweat2.provider_factor("hard"), sweat2.heart_factor(None, None),
                                         sweat2.movement_factor("workout", None, 40))
    assert hard_only == D("1.048")  # 0.4 x 1.12 + 0.4 + 0.2, not 1.12
    easy_only = sweat2.effort_multiplier(sweat2.provider_factor("easy"), F("1.00", "unavailable"), F("1.00", "unavailable"))
    assert easy_only == D("0.960")


def test_worked_examples_from_the_specification():
    # 40 minutes, moderate, no heart rate, no distance: 40 points.
    neutral = sweat2.effort_multiplier(sweat2.provider_factor("moderate"), sweat2.heart_factor(None, None),
                                       sweat2.movement_factor("workout", None, 40))
    assert total(item(minutes=40, multiplier=str(neutral))).total == 40
    # 40-minute hard run, 10% above the personal reference, 11 km/h.
    strong = sweat2.effort_multiplier(sweat2.provider_factor("hard"), sweat2.heart_factor(summary(dense(154), 30), REFERENCE),
                                      sweat2.movement_factor("run", 7.4, 40))
    assert strong == D("1.108") and total(item(minutes=40, multiplier=str(strong))).total == 44
    # An easy 40-minute walk still earns real credit, and less than the run.
    easy = sweat2.effort_multiplier(sweat2.provider_factor("easy"), sweat2.heart_factor(None, None),
                                    sweat2.movement_factor("walk", 3.0, 40))  # 4.5 km/h: an ordinary walking pace
    assert easy == D("0.960") and total(item(minutes=40, multiplier=str(easy))).total == 38


# ---------- Evidence Index ----------


def index(**kw):
    base = dict(gates_passed=True, provider_source="confirmed", overlap_resolved=False, movement_observed=False, heart=None)
    return sweat2.evidence_index(**{**base, **kw})


def test_evidence_weights_add_up_to_100():
    assert sum(part["max"] for part in sweat2.EVIDENCE.values()) == 100
    full = index(movement_observed=True, heart=summary(dense()))
    assert full["index"] == 100 and full["label"] == "strong" and full["limits"] == []


def test_no_heart_rate_and_no_distance_is_67_limited_and_still_eligible():
    found = index()
    assert found["index"] == 67 and found["label"] == "limited" and found["limits"] == ["no_heart_rate"]
    by = {p["key"]: p for p in found["parts"]}
    assert (by["physiological"]["points"], by["physiological"]["state"], by["physiological"]["reason"]) == (0, "unavailable", "not_observed")
    assert (by["movement"]["points"], by["movement"]["state"]) == (7, "unavailable")


def test_strong_needs_exercise_tagged_coverage_and_enough_samples():
    assert index(heart=summary(dense(minutes=15)))["label"] == "strong"  # 50% coverage, 30 samples
    assert index(heart=summary(dense(minutes=15)))["index"] == 81  # 35 + 25 + 7 + (7 coverage + 5 tagged + 0 spread + 2 clean)
    low = index(heart=summary(dense(minutes=14)))
    assert low["label"] == "limited" and "low_coverage" in low["limits"]
    background = index(heart=summary(dense(source="awake")))
    assert background["label"] == "limited" and background["limits"] == ["background_only"] and background["index"] == 87
    few = index(heart=summary([hr(60 * m + 5) for m in range(6)], minutes=10))  # 60% coverage but only 6 samples
    assert few["label"] == "limited" and few["limits"] == ["few_samples"]


def test_third_party_provenance_is_scored_lower_and_never_strong():
    found = index(provider_source="live_third_party_heart_rate", movement_observed=True, heart=summary(dense()))
    assert found["index"] == 85 and found["label"] == "limited" and found["limits"] == ["third_party_source"]


def test_a_high_index_never_rescues_a_failed_gate():
    found = index(gates_passed=False, provider_source="manual", movement_observed=True, heart=summary(dense()))
    assert found["label"] == "rejected" and found["index"] == 40  # heart rate and distance present, still rejected
    assert index(gates_passed=False)["label"] == "rejected"


def test_the_index_never_falls_when_the_evidence_gets_better():
    by_coverage = [index(heart=summary(dense(minutes=m)))["index"] for m in range(0, 31)]
    assert by_coverage == sorted(by_coverage)
    assert index(heart=summary(dense()))["index"] > index(heart=summary(dense(source="awake")))["index"]
    assert index(movement_observed=True)["index"] > index()["index"]
    assert index(heart=summary(dense()))["index"] > index(heart=summary(dense() + [hr(30, 999)]))["index"]  # dropped samples cost 2
    assert index()["index"] > index(overlap_resolved=True)["index"]


def test_pending_heart_rate_is_labelled_pending():
    found = index(heart_pending=True)
    assert found["label"] == "pending" and {p["key"]: p["state"] for p in found["parts"]}["physiological"] == "pending"


# ---------- rules identity ----------


def test_v2_rules_have_their_own_version_and_fingerprint_and_leave_v1_alone():
    assert sweat2.RULES_VERSION == "proof-of-sweat-v2" and sweat2.TEMPLATE == "proof_of_sweat_v2"
    assert len(sweat2.rules_fingerprint()) == 64 and sweat2.rules_fingerprint() != sweat.rules_fingerprint()
    # v1's fingerprint is locked onchain by existing challenges: it must never move.
    assert sweat.rules_fingerprint() == "43143b257a0d5e734c25378000ce858aaeb9d53918d12cbfdb469674672ab180"
    # v2's is locked by every v2 challenge: changing a constant must come with a new RULES_VERSION and this value.
    assert sweat2.rules_fingerprint() == "b9bd8375b87d6c704a54dc0fbd48121f31595c344ce853935b63eb7708c661a6"
    assert sweat2.rules()["gates"] == sweat.rules()


# ---------- evidence-adjusted effort bonus ----------


@pytest.mark.parametrize("index_, share", [(100, "1.00"), (90, "1.00"), (89, "0.85"), (75, "0.85"), (74, "0.65"),
                                           (67, "0.65"), (50, "0.65"), (49, "0.40"), (0, "0.40")])
def test_reliability_steps(index_, share):
    assert sweat2.reliability(index_) == D(share)


def test_reliability_never_falls_as_the_index_rises():
    shares = [sweat2.reliability(i) for i in range(0, 101)]
    assert shares == sorted(shares)


def final(base_minutes, multiplier, index_):
    """Final points for one workout on its own day."""
    m = sweat2.final_multiplier(D(multiplier), sweat2.reliability(index_))
    return total(item(minutes=base_minutes, multiplier=str(m))).days[0].contribution


def test_final_is_base_plus_the_bonus_the_evidence_supports():
    # The message's shape: base 40, effort x1.108 -> potential bonus 4.32.
    assert final(40, "1.108", 100) == D("44.32")  # all of it
    assert final(40, "1.108", 82) == D("43.672")  # 85%: 40 + 3.672
    assert final(40, "1.108", 67) == D("42.808")  # 65%
    assert final(40, "1.108", 40) == D("41.728")  # 40%
    assert final(40, "1.000", 40) == D("40")  # nothing to adjust: base is untouched


def test_same_effort_different_evidence_gives_different_bonuses_but_the_same_base():
    bonuses = [final(60, "1.128", i) - 60 for i in (95, 80, 60, 30)]
    assert bonuses == sorted(bonuses, reverse=True) and len(set(bonuses)) == 4
    assert all(b > 0 for b in bonuses)  # weak evidence trims the bonus; it never turns it into a penalty


def test_weak_evidence_also_softens_an_easy_label():
    assert final(40, "0.960", 100) == D("38.4") and final(40, "0.960", 67) == D("38.96")
    assert final(40, "0.960", 67) < 40  # softened towards neutral, never past it


def test_the_bonus_is_bounded_whatever_the_signals_say():
    top = sweat2.effort_multiplier(F("9"), F("9"), F("9"))
    assert top == D("1.250") and final(60, str(top), 100) == D("75")  # at most +25% of base, by the clamp
    real = sweat2.effort_multiplier(sweat2.provider_factor("hard"), sweat2.heart_factor(summary(dense(250)), REFERENCE),
                                    sweat2.movement_factor("run", 12, 30))
    assert real == D("1.128")  # the most the real factors can reach: +12.8%
    assert total(item(minutes=600, multiplier="1.250")).total == 139  # and a whole day is capped by the bands: 111 x 1.25


def test_more_samples_or_a_higher_pulse_do_not_buy_points_on_their_own():
    one_per_minute = summary([hr(60 * m + 5, 150) for m in range(30)])
    ten_per_minute = summary([hr(60 * m + s, 150) for m in range(30) for s in range(0, 60, 6)])
    assert sweat2.heart_factor(one_per_minute, REFERENCE).value == sweat2.heart_factor(ten_per_minute, REFERENCE).value
    assert index(heart=one_per_minute)["index"] == index(heart=ten_per_minute)["index"]
    low, high = summary(dense(110)), summary(dense(190))
    assert index(heart=low)["index"] == index(heart=high)["index"]  # the index is blind to how fast the heart beat
    assert sweat2.heart_factor(summary([hr(10, 200)]), REFERENCE).value == D("1.00")  # one high reading: neutral
