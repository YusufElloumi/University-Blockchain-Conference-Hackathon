"""Proof of Sweat v1 rules (api/sweat.py) and Oura normalization. Pure functions, synthetic data, no network."""

from datetime import datetime, timedelta, timezone

import pytest

import scoring
import sweat
from fitness import oura_sync

START = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
END = START + timedelta(days=7)
NOW = END + timedelta(hours=1)


def wk(ref="a", minutes=30, at=60, type="run", source="confirmed", km=None, provider="oura"):
    """A workout starting `at` minutes after the challenge start."""
    begin = START + timedelta(minutes=at)
    return sweat.Workout(ref, provider, type, source, begin, begin + timedelta(minutes=minutes), km)


def results(workout, now=NOW):
    return {c.code: (c.result, c.reason) for c in sweat.assess(workout, now)}


def total(*workouts):
    return sweat.score([sweat.Item(w, sweat.VERIFIED) for w in workouts], START, END)


# ---------- mandatory checks ----------


@pytest.mark.parametrize("source", ["confirmed", "autodetected", "workout_heart_rate", "live_oura_heart_rate",
                                    "live_third_party_heart_rate"])
def test_recorded_sources_pass_every_mandatory_check(source):
    checks = sweat.assess(wk(source=source, km=5), NOW)
    assert sweat.first_failure(checks) is None
    assert [c.code for c in checks] == ["provider", "provenance", "activity", "timestamps", "duration", "plausibility"]


@pytest.mark.parametrize("source, reason", [("manual", "manual_entry"), ("imported_from_somewhere", "unknown_source"),
                                            (None, "unknown_source"), ("", "unknown_source")])
def test_manual_and_unknown_sources_are_rejected(source, reason):
    assert results(wk(source=source))["provenance"] == (sweat.FAILED, reason)


def test_arriving_through_another_provider_is_not_enough():
    assert results(wk(provider="mock"))["provider"] == (sweat.FAILED, "unauthorized_provider")


def test_unsupported_activity_is_named_not_guessed():
    assert results(wk(type=None))["activity"] == (sweat.FAILED, "unsupported_activity")


def test_minimum_duration_is_ten_minutes():
    assert results(wk(minutes=9.99))["duration"] == (sweat.FAILED, "under_minimum")
    assert results(wk(minutes=10))["duration"] == (sweat.PASSED, None)


def test_invalid_intervals_are_rejected():
    begin = START + timedelta(hours=1)
    backwards = sweat.Workout("a", "oura", "run", "confirmed", begin, begin - timedelta(minutes=5))
    assert results(backwards)["timestamps"] == (sweat.FAILED, "ends_before_start")
    assert results(wk(minutes=25 * 60))["timestamps"] == (sweat.FAILED, "too_long")
    assert results(wk(), now=START)["timestamps"] == (sweat.FAILED, "in_the_future")
    missing = sweat.Workout("a", "oura", "run", "confirmed", None, begin)
    assert sweat.first_failure(sweat.assess(missing, NOW)) == "missing_time"
    naive = sweat.Workout("a", "oura", "run", "confirmed", begin.replace(tzinfo=None), begin.replace(tzinfo=None))
    assert sweat.first_failure(sweat.assess(naive, NOW)) == "missing_time"


@pytest.mark.parametrize("type, km, ok", [("run", 12.4, True), ("run", 13, False), ("walk", 5.1, False),
                                          ("ride", 39, True), ("swim", 4.1, False), ("workout", 40, True)])
def test_speed_caps_per_category(type, km, ok):  # 30 minutes each
    assert (results(wk(type=type, km=km))["plausibility"][0] == sweat.PASSED) is ok


def test_missing_distance_never_rejects_but_bad_distance_does():
    assert results(wk(km=None))["plausibility"] == (sweat.PASSED, "no_distance")
    assert results(wk(km=-1))["plausibility"] == (sweat.FAILED, "invalid_distance")
    assert results(wk(km=float("nan")))["plausibility"] == (sweat.FAILED, "invalid_distance")


# ---------- heart-rate evidence ----------


def hr(second, bpm=140, source="workout", begin=START + timedelta(minutes=60)):
    return {"timestamp": (begin + timedelta(seconds=second)).isoformat(), "bpm": bpm, "source": source}


def evidence(samples, minutes=30, source="confirmed"):
    w = wk(minutes=minutes, source=source)
    found = sweat.heart_evidence(samples, w.start, w.end)
    return found, sweat.evidence_check(found, source)


def test_no_heart_rate_is_limited_evidence_not_a_failure():
    found, check = evidence([])
    assert (found.bins_total, found.bins_covered) == (30, 0)
    assert (check.result, check.reason) == (sweat.LIMITED, "no_heart_rate")


def test_strong_evidence_needs_half_the_minutes_covered():
    assert evidence([hr(60 * m) for m in range(15)])[1].result == sweat.PASSED  # 15 of 30 minutes
    found, check = evidence([hr(60 * m) for m in range(14)])
    assert found.coverage < 0.5 and (check.result, check.reason) == (sweat.LIMITED, "low_coverage")


def test_many_samples_in_one_minute_are_one_minute_of_evidence():
    found, check = evidence([hr(s) for s in range(0, 60)])  # 60 samples, all inside the first minute
    assert found.bins_covered == 1 and check.reason == "low_coverage"


def test_a_short_workout_needs_a_meaningful_number_of_covered_minutes():
    found, check = evidence([hr(60 * m) for m in range(4)], minutes=6)  # 4 of 6 minutes: over half, but only 4
    assert found.coverage > 0.5 and check.reason == "low_coverage"


def test_background_only_samples_are_limited():
    _, check = evidence([hr(60 * m, source="awake") for m in range(30)])
    assert (check.result, check.reason) == (sweat.LIMITED, "background_only")


def test_malformed_and_out_of_range_samples_are_ignored_with_a_warning():
    junk = [{"timestamp": "not a time", "bpm": 150, "source": "workout"}, hr(30, bpm=None), hr(90, bpm="150"),
            hr(150, bpm=5), hr(210, bpm=400), hr(270, bpm=True), "nonsense", {"bpm": 120}]
    found, check = evidence(junk)
    assert found.bins_covered == 0 and found.warning and check.reason == "no_heart_rate"
    found, check = evidence(junk + [hr(60 * m) for m in range(20)])
    assert (check.result, check.reason) == (sweat.PASSED, "quality_warning")


def test_samples_outside_the_workout_do_not_count():
    found, _ = evidence([hr(-60), hr(30 * 60), hr(31 * 60)])  # before the start, at the end, after the end
    assert found.bins_covered == 0 and not found.warning


def test_a_short_last_minute_is_still_a_bin():
    w = wk(minutes=10.5)
    assert sweat.heart_evidence([], w.start, w.end).bins_total == 11


def test_heart_rate_level_never_decides_anything():
    low = evidence([hr(60 * m, bpm=95) for m in range(30)])[1]
    high = evidence([hr(60 * m, bpm=185) for m in range(30)])[1]
    assert low.result == high.result == sweat.PASSED


def test_third_party_heart_rate_is_capped_at_limited():
    _, check = evidence([hr(60 * m) for m in range(30)], source="live_third_party_heart_rate")
    assert (check.result, check.reason) == (sweat.LIMITED, "third_party_source")


def test_evidence_not_fetched_yet_is_pending_and_unavailable_is_limited():
    assert sweat.evidence_check(None, "confirmed").result == sweat.PENDING
    assert sweat.evidence_check(None, "confirmed", unavailable=True).reason == "heart_rate_unavailable"


# ---------- scoring ----------


@pytest.mark.parametrize("minutes, points", [(9, 0), (10, 1), (19, 1), (20, 2), (40, 4), (59, 5), (60, 6), (120, 6)])
def test_one_point_per_ten_minutes_capped_at_six(minutes, points):
    assert total(wk(minutes=minutes)).total == points


def test_separate_workouts_add_up_without_rounding_each_one_up():
    assert total(wk("a", 15, at=60), wk("b", 25, at=200)).total == 4  # 40 minutes
    assert total(wk("a", 15, at=60), wk("b", 14, at=200)).total == 2  # 29 minutes, not 1 + 1 rounded up


def test_overlapping_workouts_count_each_minute_once():
    sheet = total(wk("a", 30, at=60), wk("b", 30, at=75))  # 60-90 and 75-105: 45 minutes in all
    assert sheet.total == 4 and sheet.eligible_minutes == 45
    assert sheet.lines["a"].points == 3 and sheet.lines["b"].points == 1
    assert (sheet.lines["b"].overlap, sheet.lines["b"].reason) == (sweat.LIMITED, "partly_overlapping")


def test_a_fully_covered_copy_earns_nothing():
    sheet = total(wk("a", 40, at=60), wk("b", 20, at=70))
    assert sheet.total == 4 and sheet.lines["b"].status == sweat.REJECTED and sheet.lines["b"].reason == "duplicate_time"


def test_the_same_record_twice_counts_once():
    assert total(wk("a", 30), wk("a", 30)).total == 3


def test_result_does_not_depend_on_import_order():
    a, b, c = wk("a", 30, at=60), wk("b", 30, at=75), wk("c", 20, at=300)
    assert total(a, b, c).total == total(c, b, a).total == 6
    assert total(c, b, a).lines["a"].points == 3


def test_a_workout_across_a_day_boundary_feeds_both_days():
    sheet = total(wk("a", 50, at=24 * 60 - 25))  # 25 minutes in day 0, 25 in day 1
    assert {d: day.points for d, day in sheet.days.items()} == {0: 2, 1: 2}
    assert sheet.lines["a"].days == {0: 1500, 1: 1500} and sheet.lines["a"].points == 4


def test_the_daily_cap_applies_per_day():
    sheet = total(wk("a", 90, at=60), wk("b", 90, at=24 * 60 + 60))
    assert sheet.total == 12 and sheet.days[0].points == 6


def test_only_time_inside_the_challenge_counts():
    early = total(wk("a", 40, at=-25))  # 25 minutes before the start, 15 after
    assert early.total == 1 and early.lines["a"].eligible_minutes == 15
    late = total(wk("a", 40, at=7 * 24 * 60 - 12))  # 12 minutes before the end
    assert late.total == 1
    assert total(wk("a", 40, at=-33)).lines["a"].reason == "under_minimum_in_window"  # 7 minutes inside
    assert total(wk("a", 40, at=-60)).lines == {}  # wholly before the challenge: not its business


def test_rejected_and_pending_workouts_score_nothing():
    items = [sweat.Item(wk("a", 30), sweat.REJECTED, "manual_entry"), sweat.Item(wk("b", 30, at=200), sweat.PENDING)]
    sheet = sweat.score(items, START, END)
    assert sheet.total == 0 and sheet.lines["a"].reason == "manual_entry" and sheet.lines["b"].status == sweat.PENDING
    assert sheet.rejected == {"a": "manual_entry"}


def test_scoring_ignores_distance_and_category():
    assert total(wk(type="ride", km=30, minutes=40)).total == total(wk(type="walk", km=2, minutes=40)).total == 4


# ---------- rules identity ----------


def test_rules_are_versioned_and_fingerprinted():
    assert sweat.RULES_VERSION == "proof-of-sweat-v1" and len(sweat.rules_fingerprint()) == 64
    assert sweat.rules_fingerprint() == sweat.rules_fingerprint() != scoring.rules_fingerprint()
    assert sweat.rules()["heart_rate"]["affects_points"] is False


# ---------- Oura normalization ----------


@pytest.mark.parametrize("name, category", [
    ("running", "run"), ("Running", "run"), ("walking", "walk"), ("hiking", "hike"), ("cycling", "ride"),
    ("indoorCycling", "ride"), ("indoor_cycling", "ride"), ("swimming", "swim"), ("strengthTraining", "workout"),
    ("HIIT", "workout"), ("yoga", "workout"), ("crossCountrySkiing", "workout"),
    ("houseWork", None), ("meditation", None), ("other", None), ("", None), (None, None), (42, None),
])
def test_oura_activities_map_explicitly(name, category):
    assert oura_sync.category_of(name) == category


def raw(**changes):
    return {"id": "wk-synthetic-1", "activity": "running", "source": "confirmed", "day": "2026-11-17",
            "start_datetime": "2026-11-17T07:00:00-06:00", "end_datetime": "2026-11-17T07:40:00-06:00",
            "intensity": "moderate", "calories": 400, "distance": 8123.0, "label": None, **changes}


def test_normalize_keeps_only_what_is_needed_in_utc():
    fields = oura_sync.normalize(raw())
    assert fields["start_time"] == datetime(2026, 11, 17, 13, 0, tzinfo=timezone.utc) and fields["minutes"] == 40
    assert fields["distance_km"] == 8.123 and fields["activity_type"] == "run" and fields["provider_source"] == "confirmed"
    assert "wk-synthetic-1" not in str(fields) and len(fields["provider_ref"]) == 64
    assert not {"calories", "intensity", "label", "id"} & set(fields)


def test_normalize_handles_offsets_midnight_and_daylight_saving():
    across = oura_sync.normalize(raw(start_datetime="2026-11-17T23:50:00+02:00", end_datetime="2026-11-18T00:20:00+02:00"))
    assert across["start_time"] == datetime(2026, 11, 17, 21, 50, tzinfo=timezone.utc) and across["minutes"] == 30
    # The night US clocks go back: 01:30 happens twice, told apart only by the offset. Real length: 90 minutes.
    dst = oura_sync.normalize(raw(start_datetime="2026-11-01T01:30:00-05:00", end_datetime="2026-11-01T02:00:00-06:00"))
    assert dst["minutes"] == 90


def test_normalize_survives_missing_and_malformed_fields():
    assert oura_sync.normalize({"activity": "running"}) is None and oura_sync.normalize("nonsense") is None
    sparse = oura_sync.normalize({"id": "x", "start_datetime": "garbage", "distance": "far", "activity": 7})
    assert sparse["start_time"] is None and sparse["distance_km"] is None and sparse["activity_type"] is None
    assert sparse["minutes"] == 0.0
    no_offset = oura_sync.normalize(raw(start_datetime="2026-11-17T07:00:00"))
    assert no_offset["start_time"] is None  # a time with no offset cannot be placed, so it is not trusted


def test_an_edit_changes_the_content_hash_but_not_the_reference():
    before, after = oura_sync.normalize(raw()), oura_sync.normalize(raw(source="manual"))
    assert before["provider_ref"] == after["provider_ref"] and before["content_hash"] != after["content_hash"]
    assert oura_sync.normalize(raw(calories=999))["content_hash"] == before["content_hash"]  # fields we don't keep
