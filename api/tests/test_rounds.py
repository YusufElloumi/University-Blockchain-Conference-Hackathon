"""Prediction rounds on (a pretend) Gemini, and league-stats scoring from an uploaded CSV. No network needed."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

import db
import pickrounds
from test_stage4 import CHALLENGE, WALLETS, client, fakes, make_token, state  # noqa: F401
from test_stage6 import fake_chain  # noqa: F401

NOW = datetime.now(timezone.utc)


def z(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def game(ticker, sport="basketball", league="Pro Basketball", hours=2, sides=(("Home", "0.59", "0.61"), ("Away", "0.39", "0.41")),
         volume="100", scope="full_contest", winner=None, status="active"):
    starts = NOW + timedelta(hours=hours)
    path = ["Sports", "Soccer", league] if sport == "soccer" else ["Sports", league]
    return {
        "ticker": ticker, "title": f"{ticker} game", "category": "Sports", "status": status,
        "startTime": z(starts), "expiryDate": z(starts + timedelta(hours=36)), "volume24h": volume, "volume": volume,
        "subcategory": {"name": league, "path": path},
        "sportsMarket": {"sport": sport, "type": "moneyline", "scope": {"type": scope}},
        "contracts": [
            {"id": f"{ticker}-{i}", "label": label, "prices": {"bestBid": bid, "bestAsk": ask},
             **({"resolutionSide": "yes" if label == winner else "no"} if winner else {})}
            for i, (label, bid, ask) in enumerate(sides)
        ],
    }


@pytest.fixture(autouse=True)
def gemini(monkeypatch):
    """A pretend Gemini: `world["events"]` is what it lists. Filters by sport and category like the real one."""
    world = {"events": [game("NBA1")], "down": False}

    def fetch(path="", params=None):
        if world["down"]:
            raise RuntimeError("gemini is down")
        if path:
            return next(e for e in world["events"] if e["ticker"] == path.lstrip("/"))
        params = params or {}
        found = world["events"]
        if "sport" in params:
            found = [e for e in found if (e.get("sportsMarket") or {}).get("sport") == params["sport"]]
        if "category" in params:
            found = [e for e in found if e.get("category") == params["category"]]
        return {"data": found}

    monkeypatch.setattr(pickrounds, "fetch", fetch)
    monkeypatch.setattr(pickrounds, "_cache", {})
    return world


def create(client, **settings):
    body = {"address": CHALLENGE, "name": "Hockey league", "mode": "league", "organizer_name": "Ice Box",
            "pick_themes": ["basketball"], "round_hours": 24, **settings}
    reply = client.post("/challenges", json=body, headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    for who in ("maya", "sam"):
        client.post("/invites/redeem", json={"code": reply.json()["invite_code"]}, headers=make_token(who))
        assert client.post(f"/challenges/{CHALLENGE}/join", json={"consent": True}, headers=make_token(who)).status_code == 200
    return reply.json()


def pick(client, who, option, number=None):
    rounds = state(client, who)["rounds"]["list"]
    number = number or rounds[-1]["number"]
    return client.post(f"/challenges/{CHALLENGE}/rounds/{number}/pick", json={"option_id": option},
                       headers=make_token(who))


def set_round(**values):
    with db.SessionLocal() as session:
        round_ = session.scalar(select(db.PickRound))
        for key, value in values.items():
            setattr(round_, key, value)
        session.commit()


# ---------- the maths ----------


def test_points_are_one_over_probability_with_a_cap():
    assert pickrounds.pick_points(0.5) == 2
    assert pickrounds.pick_points(0.25) == 4
    assert pickrounds.pick_points(0.7) == 1.4
    assert pickrounds.pick_points(0.01) == pickrounds.MAX_PICK_POINTS


def test_probabilities_use_the_middle_price_and_add_up_to_one():
    chances = pickrounds.probabilities(game("X", sides=(("A", "0.69", "0.70"), ("Tie", "0.17", "0.18"), ("B", "0.12", "0.13")))["contracts"])
    assert abs(sum(chances) - 1) < 1e-9 and round(chances[0], 2) == 0.70


def test_thin_markets_are_skipped():
    assert pickrounds.probabilities(game("X", sides=(("A", "0.40", "0.60"), ("B", "0.40", "0.60")))["contracts"]) is None
    assert pickrounds.probabilities([{"prices": {"lastTradePrice": "0.5"}}, {"prices": {}}]) is None


# ---------- choosing the market ----------


def choose(themes, number=0, end_hours=24 * 5, start=NOW, now=NOW, used=()):
    pickrounds._cache.clear()  # the scenario changed since the last call
    return pickrounds.choose_market(themes, number, (start, start + timedelta(days=1)), NOW + timedelta(hours=end_hours),
                                    set(used), now)


def test_same_day_beats_later_and_big_leagues_rank_higher(gemini):
    gemini["events"] = [
        game("CBB", league="College Basketball", hours=3),
        game("NBA", hours=4),
        game("NBA_TOMORROW", hours=26),
    ]
    assert choose(["basketball"])["ticker"] == "NBA"
    gemini["events"] = [game("CBB", league="College Basketball", hours=3), game("NBA_TOMORROW", hours=26)]
    pickrounds._cache.clear()
    picked = pickrounds.choose_market(["basketball"], 0, (NOW, NOW + timedelta(days=7)), NOW + timedelta(days=7), set(), NOW)
    assert picked["ticker"] == "CBB"  # today's game first, even from a smaller league


def test_soccer_prefers_the_big_leagues_and_offers_the_draw(gemini):
    three = (("Home", "0.44", "0.46"), ("Tie", "0.27", "0.29"), ("Away", "0.27", "0.29"))
    gemini["events"] = [game("MLS", "soccer", "MLS", sides=three, volume="900"),
                        game("UCL", "soccer", "Champions League", sides=three, volume="10")]
    market = choose(["soccer"])
    assert market["ticker"] == "UCL" and [o["label"] for o in market["options"]] == ["Home", "Tie", "Away"]


def test_bigger_volume_wins_within_a_league(gemini):
    gemini["events"] = [game("CLOSE", volume="10", sides=(("A", "0.49", "0.51"), ("B", "0.49", "0.51"))),
                        game("BIG", volume="5000", sides=(("A", "0.69", "0.71"), ("B", "0.29", "0.31")))]
    assert choose(["basketball"])["ticker"] == "BIG"


def test_quarter_markets_started_games_and_used_games_are_skipped(gemini):
    gemini["events"] = [game("Q1", scope="quarter"), game("LIVE", hours=-1), game("SOON", hours=0.1), game("OK")]
    assert choose(["basketball"])["ticker"] == "OK"
    assert choose(["basketball"], used={"OK"}) is None


def test_a_game_must_finish_before_the_challenge_ends(gemini):
    gemini["events"] = [game("LATE", hours=3)]  # basketball lasts about 2.5 hours
    assert choose(["basketball"], end_hours=5.5)["ticker"] == "LATE"
    assert choose(["basketball"], end_hours=5.4) is None


def test_on_sunday_only_games_that_end_that_day(gemini):
    sunday = datetime(2026, 11, 22, 12, 0, tzinfo=pickrounds.EASTERN)
    early, late = sunday.replace(hour=13), sunday.replace(hour=22)  # late: 10 PM + 3.5 h is after midnight
    gemini["events"] = []
    for ticker, kick in (("EARLY", early), ("LATE", late)):
        event = game(ticker, "american_football", "Pro Football", volume="5000" if ticker == "LATE" else "1")
        event["startTime"] = z(kick.astimezone(timezone.utc))
        gemini["events"].append(event)
    market = pickrounds.choose_market(["football"], 0, (sunday, sunday + timedelta(hours=14)),
                                      sunday + timedelta(days=2), set(), sunday)
    assert market["ticker"] == "EARLY"


def test_themes_take_turns_and_fill_in_for_each_other(gemini):
    gemini["events"] = [game("NBA"), game("NHL", "hockey", "Pro Hockey")]
    assert choose(["basketball", "hockey"], number=0)["ticker"] == "NBA"
    assert choose(["basketball", "hockey"], number=1)["ticker"] == "NHL"
    gemini["events"] = [game("NBA")]
    assert choose(["basketball", "hockey"], number=1)["ticker"] == "NBA"  # no hockey today: next theme


def test_general_takes_the_most_traded_market_including_price_questions(gemini):
    ladder = {
        "ticker": "BTC1", "title": "BTC price today", "category": "Crypto", "volume24h": "9000",
        "expiryDate": z(NOW + timedelta(hours=8)),
        "contracts": [
            {"id": "BTC1-a", "label": "$90,000 or above", "prices": {"bestBid": "0.90", "bestAsk": "0.92"}},
            {"id": "BTC1-b", "label": "$95,000 or above", "prices": {"bestBid": "0.47", "bestAsk": "0.49"}},
        ],
    }
    gemini["events"] = [game("NBA", volume="100"), ladder]
    market = choose(["general"])
    assert market["ticker"] == "BTC1" and "$95,000" in market["title"]
    assert [o["label"] for o in market["options"]] == ["Yes", "No"]
    assert market["starts"] == NOW + timedelta(hours=5)  # picks lock 3 hours before it closes


def test_gemini_down_means_no_round_yet(gemini):
    gemini["down"] = True
    assert choose(["basketball"]) is None


# ---------- rounds in a challenge ----------


def test_a_round_opens_and_shows_live_odds_and_a_link(client, gemini):
    view = create(client)
    assert view["pick_themes"] == ["basketball"] and view["round_hours"] == 24 and view["round_count"] == 7
    rounds = state(client)["rounds"]
    assert rounds["total"] == 7 and len(rounds["list"]) == 1
    current = rounds["list"][0]
    assert current["number"] == 3  # the challenge started 2 days ago
    assert current["market_url"] == "https://www.gemini.com/predictions/NBA1"
    assert [(o["label"], o["chance"], o["pays"]) for o in current["options"]] == [("Home", 60, 1.7), ("Away", 40, 2.5)]


def test_settings_are_checked(client):
    body = {"address": CHALLENGE, "name": "x", "mode": "private"}
    assert client.post("/challenges", json={**body, "pick_themes": ["basketball"]}, headers=make_token("maya")).status_code == 400
    assert client.post("/challenges", json={**body, "pick_themes": ["darts"], "round_hours": 24}, headers=make_token("maya")).status_code == 422
    assert client.post("/challenges", json={**body, "scoring_source": "league_stats"}, headers=make_token("maya")).status_code == 400


def test_picks_lock_the_price_stay_hidden_and_pay_when_right(client, gemini, fake_chain):
    create(client)
    assert pick(client, "maya", "NBA1-0").status_code == 200
    gemini["events"][0]["contracts"][0]["prices"] = {"bestBid": "0.74", "bestAsk": "0.76"}  # the odds move
    gemini["events"][0]["contracts"][1]["prices"] = {"bestBid": "0.24", "bestAsk": "0.26"}
    pickrounds._cache.clear()
    assert pick(client, "sam", "NBA1-1").json()["yours"]["chance"] == 25
    round_ = state(client)["rounds"]["list"][0]
    assert round_["everyone"] is None and round_["picks_made"] == 2  # hidden until kick-off
    assert round_["yours"]["pick"] == "Home"

    set_round(locks_at=NOW - timedelta(hours=3), expected_end=NOW - timedelta(minutes=1))
    gemini["events"][0] = game("NBA1", winner="Away")
    assert pick(client, "maya", "NBA1-1").status_code == 409  # locked
    after = state(client)
    round_ = after["rounds"]["list"][0]
    assert round_["status"] == "resolved" and round_["winner"] == "Away"
    assert {p["name"]: p["points"] for p in round_["everyone"]} == {"maya": 0, "sam": 4}
    assert {p["name"]: (p["points"], p["pick_points"]) for p in after["players"]} == {"maya": (0, 0), "sam": (4, 4)}


def test_settlement_waits_for_results_then_voids_them(client, gemini, fakes, fake_chain):
    create(client)
    pick(client, "sam", "NBA1-1")
    set_round(locks_at=NOW - timedelta(hours=3), expected_end=NOW - timedelta(minutes=1))
    fakes.end_time = int(NOW.timestamp()) - 60
    with db.SessionLocal() as session:
        session.scalar(select(db.Challenge)).end_time = NOW - timedelta(minutes=1)
        session.commit()
    reply = client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya"))
    assert reply.status_code == 409 and "Gemini" in reply.json()["detail"]

    fakes.end_time = int((NOW - pickrounds.RESULT_WAIT - timedelta(minutes=1)).timestamp())
    reply = client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    with db.SessionLocal() as session:
        assert session.scalar(select(db.PickRound)).status == "void"
        sheet = json.loads(session.scalar(select(db.Challenge)).score_sheet)
    assert sheet["prediction_rounds"]["rounds"][0]["status"] == "void"
    assert sorted(fake_chain[-1][1]) == sorted([WALLETS["maya"], WALLETS["sam"]])  # 0-0: they split


def test_a_settled_pick_counts_in_the_payout(client, gemini, fakes, fake_chain):
    create(client)
    pick(client, "sam", "NBA1-1")
    set_round(locks_at=NOW - timedelta(hours=3), expected_end=NOW - timedelta(minutes=1))
    gemini["events"][0] = game("NBA1", winner="Away")
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 200 and reply.json()["winners"] == [WALLETS["sam"]]


# ---------- league stats ----------

SHEET = """game_date,player_name,jersey_number,team,goals,assists,points
{d},Maya,12,Blue Lines,2,1,3
{d},Sam Ortíz,7,Blue Lines,0,2,
{d},Zed Ringer,9,Red Wings,5,5,10
"""


def today():
    return datetime.now(timezone.utc).astimezone(pickrounds.CENTRAL).date().isoformat()


def stats_event(client, **settings):
    return create(client, scoring_source="league_stats", pick_themes=[], round_hours=None, **settings)


def test_template_and_grok_prompt(client):
    reply = client.get("/stats/template.csv")
    assert reply.status_code == 200 and reply.text.startswith("game_date,player_name,jersey_number,team,goals,assists,points")
    stats_event(client)
    summary = client.get(f"/challenges/{CHALLENGE}/stats", headers=make_token("maya")).json()
    assert summary["grok_url"] == "https://grok.com" and "game_date,player_name" in summary["grok_prompt"]


def test_upload_matches_names_and_scores_the_league(client):
    stats_event(client, stat_weights={"goals": 2, "assists": 1})
    reply = client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": SHEET.format(d=today())}, headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert body["rows"] == 3 and body["unmatched"] == ["Sam Ortíz", "Zed Ringer"]  # "sam" is not "Sam Ortiz"
    players = {p["name"]: p["user_id"] for p in body["players"]}
    reply = client.post(f"/challenges/{CHALLENGE}/stats/match", json={"matches": {players["sam"]: "sam ortiz"}},
                        headers=make_token("maya"))
    assert reply.status_code == 200 and reply.json()["unmatched"] == ["Zed Ringer"]
    table = {p["name"]: p for p in state(client)["players"]}
    assert table["maya"]["points"] == 5 and table["sam"]["points"] == 2 and table["sam"]["ticks"] == []


def test_reuploading_a_date_replaces_it_and_old_dates_are_skipped(client):
    stats_event(client)
    client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": SHEET.format(d=today())}, headers=make_token("maya"))
    fixed = f"game_date,player_name,goals,assists\n{today()},Maya,0,0\n2020-01-01,Maya,9,9\n"
    body = client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": fixed}, headers=make_token("maya")).json()
    assert body["rows"] == 1 and body["skipped_outside_dates"] == 1
    assert {p["name"]: p["points"] for p in state(client)["players"]}["maya"] == 0


def test_bad_sheets_are_explained(client):
    stats_event(client)
    for csv, words in [
        ("name,goals\nMaya,1", "header"),
        (f"game_date,player_name,goals\n{today()},Maya,lots", "Line 2"),
        ("game_date,player_name,goals\n21/11/2026,Maya,1", "2026-11-21"),
    ]:
        reply = client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": csv}, headers=make_token("maya"))
        assert reply.status_code == 400 and words in reply.json()["detail"]


def test_only_the_organizer_manages_stats_and_workouts_dont_count(client):
    stats_event(client)
    assert client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": SHEET.format(d=today())},
                       headers=make_token("sam")).status_code == 403
    reply = client.post("/me/activities", json={"type": "run", "minutes": 30}, headers=make_token("sam"))
    assert reply.json()["challenges"][0]["counted"] is False


def test_one_sheet_name_per_player(client):
    stats_event(client)
    client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": SHEET.format(d=today())}, headers=make_token("maya"))
    players = {p["name"]: p["user_id"] for p in client.get(f"/challenges/{CHALLENGE}/stats", headers=make_token("maya")).json()["players"]}
    reply = client.post(f"/challenges/{CHALLENGE}/stats/match", json={"matches": {players["sam"]: "Maya"}},
                        headers=make_token("maya"))
    assert reply.status_code == 400


def test_score_sheet_records_a_hash_of_the_stats(client, fake_chain):
    stats_event(client)
    client.post(f"/challenges/{CHALLENGE}/stats", json={"csv": SHEET.format(d=today())}, headers=make_token("maya"))
    assert client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya")).status_code == 200
    sheet = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("maya")).json()["sheet"]
    assert sheet["rules"] == "league_stats" and len(sheet["league_stats"]["sha256"]) == 64
