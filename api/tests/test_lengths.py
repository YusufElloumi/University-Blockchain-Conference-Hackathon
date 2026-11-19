"""Custom challenge lengths: 15 minutes to 365 days, read from the chain, with everything that depends on length."""

from datetime import datetime, timedelta, timezone

import pytest

import db
import pickrounds
import scoring
from fitness.base import Activity
from test_stage4 import CHALLENGE, client, fakes, make_token  # noqa: F401

START = datetime(2026, 11, 16, 6, 0, tzinfo=timezone.utc)
LENGTHS = {"36 hours": timedelta(hours=36), "10 days": timedelta(days=10), "365 days": timedelta(days=365)}


def run(at_hours, minutes=30, km=0.0, id=None):
    return Activity(id or f"a{at_hours}", "run", START + timedelta(hours=at_hours), minutes, km, "Watch", False)


def set_length(fakes, length, start_in=timedelta(minutes=5)):
    start = datetime.now(timezone.utc) + start_in
    fakes.start_time = int(start.timestamp())
    fakes.end_time = int((start + length).timestamp())


def create(client, **body):
    return client.post("/challenges", json={"address": CHALLENGE, "name": "Length test", "mode": "public", **body},
                       headers=make_token("maya"))


# ---------- scoring days ----------


@pytest.mark.parametrize("length, days", [
    (timedelta(minutes=15), 1),
    (timedelta(hours=24), 1),
    (timedelta(hours=36), 2),
    (timedelta(days=10), 10),
    (timedelta(days=10, minutes=1), 11),
    (timedelta(days=365), 365),
])
def test_day_count_counts_a_partial_last_day(length, days):
    assert scoring.day_count(START, START + length) == days


def test_36_hours_scores_a_short_second_day():
    end = START + LENGTHS["36 hours"]
    sheet = scoring.score_daily_mover([run(1, km=5), run(30), run(36, id="late")], START, end)
    assert {d: s.points for d, s in sheet.days.items()} == {0: 2, 1: 1}  # hour 30 is day 1, the 12-hour block
    assert sheet.rejected == {"late": "outside the challenge dates"}  # hour 36 is the end itself


def test_10_days_scores_every_day_up_to_the_last():
    end = START + LENGTHS["10 days"]
    sheet = scoring.score_daily_mover([run(24 * d + 1) for d in range(11)], START, end)
    assert sorted(sheet.days) == list(range(10)) and sheet.total == 10
    assert sheet.rejected == {"a241": "outside the challenge dates"}


def test_365_days_scores_the_last_day():
    end = START + LENGTHS["365 days"]
    sheet = scoring.score_daily_mover([run(0.5), run(24 * 364 + 23)], START, end)
    assert sorted(sheet.days) == [0, 364] and sheet.total == 2


# ---------- the range is enforced by the API, from the chain ----------


@pytest.mark.parametrize("length, ok", [
    (timedelta(minutes=14), False),
    (timedelta(minutes=15), True),
    (LENGTHS["36 hours"], True),
    (LENGTHS["10 days"], True),
    (LENGTHS["365 days"], True),
    (timedelta(days=365, minutes=1), False),
])
def test_length_must_be_15_minutes_to_365_days(client, fakes, length, ok):
    set_length(fakes, length)
    reply = create(client)
    assert reply.status_code == (200 if ok else 400), reply.text
    if not ok:
        assert "15 minutes" in reply.json()["detail"] and "365 days" in reply.json()["detail"]


# ---------- goal format: an active-days target must fit the days ----------


@pytest.mark.parametrize("name, most", [("36 hours", 2), ("10 days", 10)])
def test_active_days_goal_cannot_exceed_the_days(client, fakes, name, most):
    set_length(fakes, LENGTHS[name])
    too_many = create(client, format="goal", format_config={"metric": "active_days", "target": most + 1})
    assert too_many.status_code == 400 and f"has {most} days" in too_many.json()["detail"]
    reply = create(client, format="goal", format_config={"metric": "active_days", "target": most})
    assert reply.status_code == 200 and reply.json()["format_config"]["target"] == most


def test_365_days_allows_the_largest_goal_and_points_goals_are_not_limited_by_days(client, fakes):
    set_length(fakes, LENGTHS["36 hours"])
    assert create(client, format="goal", format_config={"metric": "points", "target": 50}).status_code == 200
    set_length(fakes, LENGTHS["365 days"])
    with db.SessionLocal() as session:
        session.query(db.Challenge).delete()
        session.commit()
    assert create(client, format="goal", format_config={"metric": "active_days", "target": 100}).status_code == 200


# ---------- prediction rounds fit inside the challenge ----------


def rounds_for(length, hours):
    challenge = db.Challenge(start_time=START, end_time=START + length, pick_themes='["basketball"]', round_hours=hours)
    count = pickrounds.round_count(challenge)
    return count, [pickrounds.window(challenge, n) for n in range(count)]


def test_36_hours_with_daily_rounds_clips_the_second_round():
    count, windows = rounds_for(LENGTHS["36 hours"], 24)
    assert count == 2
    assert windows[1] == (START + timedelta(hours=24), START + timedelta(hours=36))


def test_36_hours_with_weekly_rounds_has_one_round_ending_with_the_challenge():
    count, windows = rounds_for(LENGTHS["36 hours"], 168)
    assert count == 1 and windows[0] == (START, START + timedelta(hours=36))


def test_10_days_with_weekly_rounds_has_a_short_second_round():
    count, windows = rounds_for(LENGTHS["10 days"], 168)
    assert count == 2 and windows[1] == (START + timedelta(days=7), START + timedelta(days=10))


def test_365_days_with_daily_rounds_has_365_rounds_and_none_runs_past_the_end():
    count, windows = rounds_for(LENGTHS["365 days"], 24)
    assert count == 365
    assert all(end <= START + LENGTHS["365 days"] for _, end in windows)
    assert windows[-1] == (START + timedelta(days=364), START + timedelta(days=365))


def test_a_round_never_opens_after_the_end(client, fakes):
    """The round for "now" is found from the start; after the end there is none to open."""
    set_length(fakes, LENGTHS["36 hours"], start_in=timedelta(hours=-40))
    assert create(client, pick_themes=["basketball"], round_hours=24).status_code == 200
    with db.SessionLocal() as session:
        challenge = session.query(db.Challenge).one()
        assert pickrounds.open_due_round(session, challenge) is None


# ---------- the leaderboard's daily ticks ----------


def test_ticks_cover_only_the_days_so_far(client, fakes):
    set_length(fakes, LENGTHS["365 days"], start_in=timedelta(days=-2, hours=-1))
    assert create(client).status_code == 200
    assert client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True}, headers=make_token("maya")).status_code == 200
    board = client.get(f"/challenges/{CHALLENGE}/leaderboard", headers=make_token("maya")).json()
    rows = board if isinstance(board, list) else board.get("players", board.get("leaderboard"))
    assert len(rows[0]["ticks"]) == 3  # two full days and the one under way, never 365
