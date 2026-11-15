"""Pick'em tiebreaker: games from (a pretend) Gemini, picks, secrecy, and tie-breaking. No network needed."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import db
import pickem
from test_stage4 import CHALLENGE, WALLETS, challenge, client, fakes, make_token, state  # noqa: F401
from test_stage6 import fake_chain, workout  # noqa: F401

GAME = "NBA-DET-MIA-M"


def event(ticker=GAME, title="Detroit vs Miami", hours=5, winner=None, sides=("Detroit", "Miami")):
    starts = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat().replace("+00:00", "Z")
    contracts = [
        {"id": f"{ticker}-{i}", "label": label,
         "prices": {"bestBid": bid, "bestAsk": ask, "lastTradePrice": "0.5"},
         **({"resolutionSide": "yes" if label == winner else "no"} if winner else {})}
        for i, (label, bid, ask) in enumerate(zip(sides, ("0.37", "0.61"), ("0.39", "0.63")))
    ]
    return {"ticker": ticker, "title": title, "startTime": starts, "category": "Sports",
            "subcategory": {"name": "NBA"}, "contracts": contracts}


@pytest.fixture(autouse=True)
def gemini(monkeypatch):
    """A pretend Gemini API. `world["events"]` is what it currently lists; calls are counted."""
    world = {"events": [event()], "calls": 0, "down": False}

    def fetch(path="", params=None):
        world["calls"] += 1
        if world["down"]:
            raise RuntimeError("gemini is down")
        if path:
            return next(e for e in world["events"] if e["ticker"] == path.lstrip("/"))
        return {"data": world["events"]}

    monkeypatch.setattr(pickem, "fetch", fetch)
    monkeypatch.setattr(pickem, "_cache", {"at": 0.0, "games": []})
    return world


@pytest.fixture
def joining(fakes):
    """Puts the pretend challenge back in its joining window, when picks are allowed."""
    fakes.start_time = int(time.time()) + 600
    return fakes


def kick_off(fakes, seconds_ago):
    """Moves the start into the past, both on the pretend chain and in our stored copy of the challenge."""
    fakes.start_time = int(time.time()) - seconds_ago
    with db.SessionLocal() as session:
        session.scalar(select(db.Challenge)).start_time = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
        session.commit()


def pick(client, who, side, ticker=GAME):
    index = {"Detroit": 0, "Miami": 1}[side]
    return client.post(f"/challenges/{CHALLENGE}/pick", json={"ticker": ticker, "option_id": f"{ticker}-{index}"},
                       headers=make_token(who))


def end_now(client):
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 200
    return reply.json()


def test_games_are_two_sided_upcoming_and_show_market_odds(client, gemini):
    gemini["events"] += [
        event("PAST", "Old game", hours=-2),
        event("FAR", "Next month", hours=24 * 30),
        {**event("GOLF", "Tournament winner"), "contracts": [{"id": "a"}, {"id": "b"}, {"id": "c"}]},
    ]
    games = client.get("/pickem/games", headers=make_token("maya")).json()
    assert [g["ticker"] for g in games] == [GAME]
    assert games[0]["league"] == "NBA"
    assert [(o["label"], o["chance"]) for o in games[0]["options"]] == [("Detroit", 38), ("Miami", 62)]
    assert client.get("/pickem/games").status_code == 401


def test_games_are_cached_and_a_gemini_outage_is_a_clean_error(client, gemini):
    client.get("/pickem/games", headers=make_token("maya"))
    client.get("/pickem/games", headers=make_token("maya"))
    assert gemini["calls"] == 1
    pickem._cache["at"] = 0.0
    gemini["down"] = True
    assert client.get("/pickem/games", headers=make_token("maya")).status_code == 503


def test_a_player_can_pick_and_change_until_kick_off(client, joining, challenge):
    assert pick(client, "maya", "Detroit").json() == {
        "ticker": GAME, "game": "Detroit vs Miami", "option_id": f"{GAME}-0", "pick": "Detroit", "chance": 38}
    assert pick(client, "maya", "Miami").json()["pick"] == "Miami"
    body = state(client)["pickem"]
    assert body["open"] is True and body["made"] == 1 and body["yours"]["pick"] == "Miami"


def test_bad_picks_are_refused(client, joining, challenge):
    assert pick(client, "zoe", "Miami").status_code == 403  # not a player
    assert pick(client, "maya", "Miami", ticker="NOPE").status_code == 409
    wrong_side = client.post(f"/challenges/{CHALLENGE}/pick", json={"ticker": GAME, "option_id": "other"},
                             headers=make_token("maya"))
    assert wrong_side.status_code == 409


def test_picks_close_at_kick_off(client, challenge):
    assert pick(client, "maya", "Miami").status_code == 409  # this challenge started 2 days ago
    assert state(client)["pickem"]["open"] is False


def test_picks_are_secret_until_kick_off(client, joining, challenge):
    pick(client, "maya", "Miami")
    rows = {p["name"]: p for p in state(client, "sam")["players"]}
    assert rows["maya"]["pick"] is None and state(client, "sam")["pickem"]["yours"] is None
    kick_off(joining, seconds_ago=60)
    rows = {p["name"]: p for p in state(client, "sam")["players"]}
    assert rows["maya"]["pick"] == "Miami"


def test_a_right_pick_breaks_a_tie(client, joining, challenge, gemini, fake_chain):
    pick(client, "maya", "Detroit")
    pick(client, "sam", "Miami")
    gemini["events"] = [event(winner="Miami")]
    body = end_now(client)
    assert body["winners"] == [WALLETS["sam"]]
    sheet = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("sam")).json()["sheet"]
    assert sheet["tiebreak"]["decided"] is True and sheet["tiebreak"]["source"] == "Gemini Prediction Markets"
    assert [(p["pick"], p["correct"]) for p in sheet["tiebreak"]["picks"]] == [("Detroit", False), ("Miami", True)]


def test_points_beat_picks(client, joining, challenge, gemini, fake_chain):
    pick(client, "sam", "Miami")
    kick_off(joining, seconds_ago=3600)
    workout(client, "maya")
    gemini["events"] = [event(winner="Miami")]
    assert end_now(client)["winners"] == [WALLETS["maya"]]  # no tie, so the pick never matters


@pytest.mark.parametrize("winner, picks", [
    (None, {"maya": "Detroit", "sam": "Miami"}),      # game not settled yet
    ("Miami", {"maya": "Miami", "sam": "Miami"}),     # both right
    ("Miami", {"maya": "Detroit", "sam": "Detroit"}), # both wrong
    ("Miami", {}),                                    # nobody picked
])
def test_the_tie_stands_when_picks_cannot_separate_players(client, joining, challenge, gemini, winner, picks):
    for who, side in picks.items():
        pick(client, who, side)
    gemini["events"] = [event(winner=winner)]
    assert end_now(client)["winners"] == [WALLETS["maya"], WALLETS["sam"]]


def test_one_player_picking_right_beats_a_player_who_did_not_pick(client, joining, challenge, gemini):
    pick(client, "sam", "Miami")
    gemini["events"] = [event(winner="Miami")]
    assert end_now(client)["winners"] == [WALLETS["sam"]]


def test_a_gemini_outage_at_settlement_just_splits_the_pool(client, joining, challenge, gemini):
    pick(client, "maya", "Detroit")
    pick(client, "sam", "Miami")
    gemini["down"] = True
    assert end_now(client)["winners"] == [WALLETS["maya"], WALLETS["sam"]]
