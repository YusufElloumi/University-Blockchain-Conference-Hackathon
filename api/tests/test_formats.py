"""Competition formats: the payout rules on their own, then create -> join -> score -> settle through the API."""

import time
from datetime import datetime, timedelta, timezone

import pytest

import chain
import formats
from formats import Entry
from test_stage4 import CHALLENGE, WALLETS, client, fakes, make_token, state  # noqa: F401
from test_stage6 import fake_chain, program_checks, workout  # noqa: F401

FULL = formats.FULL


def shares(payout):
    return dict(payout.shares)


# ---------- settings ----------


def test_defaults_are_filled_in():
    assert formats.clean_config("winner_takes_all", None) == {}
    assert formats.clean_config("podium", None) == {"shares": [60, 30, 10]}
    assert formats.clean_config("goal", None) == {"metric": "active_days", "target": 5}
    assert formats.clean_config("teams", {"teams": ["  Red  ", "Blue"]}) == {"teams": ["Red", "Blue"]}


@pytest.mark.parametrize("fmt,raw", [
    ("podium", {"shares": [60, 30]}),          # does not add up to 100
    ("podium", {"shares": [30, 70]}),          # second pays more than first
    ("podium", {"shares": [100]}),             # one place is just winner takes all
    ("podium", {"shares": [50, 25, 15, 10]}),  # four places
    ("podium", {"shares": [60.5, 39.5]}),      # whole numbers only
    ("goal", {"metric": "steps", "target": 5}),
    ("goal", {"target": 0}),
    ("teams", {"teams": ["Red", "red"]}),
    ("teams", {"teams": ["Red"]}),
])
def test_bad_settings_are_refused(fmt, raw):
    with pytest.raises(formats.FormatError):
        formats.clean_config(fmt, raw)


def test_new_goals_are_active_days_only():
    assert formats.clean_config("goal", {"target": 3}) == {"metric": "active_days", "target": 3}
    with pytest.raises(formats.FormatError):  # points targets are gone for new events
        formats.clean_config("goal", {"metric": "points", "target": 3})
    for metric in ("active_days", "points"):  # stat sheets have no active days, so no goal format at all
        with pytest.raises(formats.FormatError):
            formats.clean_config("goal", {"metric": metric, "target": 3}, league_stats=True)


def test_events_that_already_locked_a_points_goal_are_still_read_and_described():
    assert "points" in formats.describe("goal", {"metric": "points", "target": 5})
    assert formats.goal_progress(Entry("a", 9, 2), {"metric": "points", "target": 5}) == 9


# ---------- payout rules ----------


def test_winner_takes_all_and_ties():
    assert shares(formats.payout("winner_takes_all", {}, [Entry("a", 5), Entry("b", 3)])) == {"a": FULL}
    tie = formats.payout("winner_takes_all", {}, [Entry("a", 5), Entry("b", 5), Entry("c", 1)])
    assert sorted(tie.wallets) == ["a", "b"] and tie.equal and sum(shares(tie).values()) == FULL


def test_podium_pays_places_in_order():
    result = formats.payout("podium", {"shares": [60, 30, 10]}, [Entry("c", 1), Entry("a", 9), Entry("b", 4), Entry("d", 0)])
    assert result.shares == [("a", 6000), ("b", 3000), ("c", 1000)] and not result.equal
    one_player_scored = formats.payout("podium", {"shares": [60, 40]}, [Entry("a", 3), Entry("b", 3)])
    assert one_player_scored.equal is False  # 2 tied players: 50/50 through settle_split is still exact


def test_podium_ties_share_the_places_they_cover():
    tied_first = formats.payout("podium", {"shares": [60, 30, 10]}, [Entry("a", 9), Entry("b", 9), Entry("c", 4)])
    assert shares(tied_first) == {"a": 4500, "b": 4500, "c": 1000}
    tied_third = formats.payout("podium", {"shares": [60, 30, 10]},
                                [Entry("a", 9), Entry("b", 5), Entry("c", 1), Entry("d", 1)])
    assert shares(tied_third) == {"a": 6000, "b": 3000, "c": 500, "d": 500}
    nobody_scored = formats.payout("podium", {"shares": [60, 30, 10]}, [Entry("a", 0), Entry("b", 0), Entry("c", 0)])
    assert sum(shares(nobody_scored).values()) == FULL
    assert sorted(shares(nobody_scored).values()) == [3333, 3333, 3334]


def test_podium_with_fewer_players_than_places_gives_the_rest_to_first():
    result = formats.payout("podium", {"shares": [60, 30, 10]}, [Entry("a", 9), Entry("b", 5)])
    assert shares(result) == {"a": 7000, "b": 3000}


def test_goal_splits_among_everyone_who_made_it():
    config = {"metric": "active_days", "target": 3}
    result = formats.payout("goal", config, [Entry("a", 2, 3), Entry("b", 9, 2), Entry("c", 3, 4)])
    assert sorted(result.wallets) == ["a", "c"] and result.equal and not result.goal_missed
    by_points = formats.payout("goal", {"metric": "points", "target": 5}, [Entry("a", 2, 3), Entry("b", 9, 2)])
    assert by_points.wallets == ["b"]


def test_goal_missed_by_everyone_returns_every_entry_fee():
    result = formats.payout("goal", {"metric": "active_days", "target": 5}, [Entry("a", 9, 4), Entry("b", 1, 0)])
    assert result.goal_missed and result.equal and sorted(result.wallets) == ["a", "b"]


def test_teams_compare_averages_and_the_winning_team_splits():
    names = ["Red", "Blue"]
    # Red: 6 and 0 (average 3). Blue: 4 (average 4). Blue wins although Red scored more in total.
    entries = [Entry("a", 6, team=0), Entry("b", 0, team=0), Entry("c", 4, team=1)]
    assert [r["name"] for r in formats.team_scores(entries, names)] == ["Blue", "Red"]
    assert formats.payout("teams", {"teams": names}, entries).wallets == ["c"]
    entries[2] = Entry("c", 2, team=1)  # Red 6+0 avg 3 vs Blue 2: Red wins, both Red players split
    result = formats.payout("teams", {"teams": names}, entries)
    assert sorted(result.wallets) == ["a", "b"] and result.equal


def test_tied_teams_split_among_everyone_on_them():
    entries = [Entry("a", 4, team=0), Entry("b", 2, team=1), Entry("c", 6, team=1)]
    result = formats.payout("teams", {"teams": ["Red", "Blue"]}, entries)
    assert sorted(result.wallets) == ["a", "b", "c"] and result.equal


# ---------- through the API ----------


@pytest.fixture
def split_chain(monkeypatch, fakes, fake_chain):
    """Also records settle_split, like the program would."""
    def settle_split(client, oracle, address, winners, groups, verifier, message, signature):
        assert time.time() >= fakes.end_time
        rules, fields = program_checks(address, winners, verifier, message, signature)
        assert rules.payout == "podium", "WrongPayoutKind"
        # The program works the shares out itself from the locked split; the signed ones must match.
        shares_bps = formats.podium_shares(rules.split_bps, len(fakes.players), groups)
        assert [p["bps"] for p in fields["payout"]] == shares_bps, "SharesNotAsCommitted"
        fakes.status = "settled"
        fake_chain.append(("settle_split", [str(w) for w in winners], shares_bps,
                           bytes.fromhex(fields["score_sheet_sha256"])))
        return "split-sig"
    monkeypatch.setattr(chain, "settle_split", settle_split)
    return fake_chain


def create(client, fmt, config=None, **extra):
    body = {"address": CHALLENGE, "name": "Format test", "mode": "public", "format": fmt, "format_config": config, **extra}
    return client.post("/challenges", json=body, headers=make_token("maya"))


def join(client, who, team=None):
    body = {"consent": True} if team is None else {"consent": True, "team": team}
    reply = client.post(f"/challenges/{CHALLENGE}/join", json=body, headers=make_token(who))
    assert reply.status_code == 200, reply.text


def end_now(client):
    reply = client.post(f"/admin/challenges/{CHALLENGE}/end-now", headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    return reply.json()


@pytest.fixture
def three_players(fakes):
    fakes.players = [WALLETS["maya"], WALLETS["sam"], WALLETS["zoe"]]


def test_bad_format_settings_are_refused_at_creation(client):
    assert create(client, "podium", {"shares": [70, 20]}).status_code == 400
    assert create(client, "golf").status_code == 422


def test_existing_events_without_a_format_are_winner_takes_all(client, fake_chain):
    assert client.post("/challenges", json={"address": CHALLENGE, "name": "Old"}, headers=make_token("maya")).json()[
        "format"] == "winner_takes_all"


def test_format_is_locked_once_created(client):
    assert create(client, "podium").json()["format"] == "podium"
    assert create(client, "goal").json()["format"] == "podium"  # a second call cannot change the rules


def test_podium_end_to_end(client, three_players, split_chain):
    view = create(client, "podium", {"shares": [50, 30, 20]}).json()
    assert view["format"] == "podium" and "50% / 30% / 20%" in view["format_summary"]
    for who in ("maya", "sam", "zoe"):
        join(client, who)
    workout(client, "sam", distance_km=5)  # 2 points
    workout(client, "zoe")  # 1 point
    players = {p["name"]: p for p in state(client)["players"]}
    assert players["sam"]["projected_share"] == 50 and players["zoe"]["projected_share"] == 30
    body = end_now(client)
    assert body["winners"] == [WALLETS["sam"], WALLETS["zoe"], WALLETS["maya"]]
    assert split_chain[-1][0] == "settle_split" and split_chain[-1][2] == [5000, 3000, 2000]
    sheet = client.get(f"/challenges/{CHALLENGE}/score-sheet", headers=make_token("sam")).json()
    assert sheet["sheet"]["format"] == {"name": "podium", "shares": [50, 30, 20]}
    assert sheet["payout"]["shares_bps"][WALLETS["sam"]] == 5000


def test_goal_end_to_end(client, split_chain):
    create(client, "goal", {"metric": "active_days", "target": 1})
    join(client, "maya")
    join(client, "sam")
    workout(client, "sam", distance_km=5)  # an active day: made it
    progress = {p["name"]: p["goal_progress"] for p in state(client)["players"]}
    assert progress == {"sam": 1, "maya": 0}  # Maya logged nothing: did not
    body = end_now(client)
    assert body["winners"] == [WALLETS["sam"]] and split_chain[-1][0] == "settle"


def test_goal_missed_returns_fees_through_an_equal_settle(client, split_chain):
    create(client, "goal", {"metric": "active_days", "target": 3})
    join(client, "maya")
    join(client, "sam")
    workout(client, "sam")
    assert state(client)["format"]["goal_missed"] is True
    body = end_now(client)
    assert sorted(body["winners"]) == sorted([WALLETS["maya"], WALLETS["sam"]])
    assert split_chain[-1][0] == "settle" and "entry fees went back" in body["note"]


def test_teams_end_to_end(client, three_players, split_chain):
    create(client, "teams", {"teams": ["Early birds", "Night owls"]})
    join(client, "maya", team=0)
    join(client, "sam", team=1)
    join(client, "zoe", team=0)
    workout(client, "sam")  # Night owls: 1 point, average 1
    workout(client, "maya", distance_km=5)  # Early birds: 2 + 0, average 1
    current = state(client)
    assert {t["name"]: t["average"] for t in current["format"]["teams"]} == {"Early birds": 1, "Night owls": 1}
    assert {p["name"]: p["team"] for p in current["players"]} == {"maya": 0, "sam": 1, "zoe": 0}
    body = end_now(client)  # teams tied: split among everyone on them
    assert sorted(body["winners"]) == sorted(WALLETS.values()) and split_chain[-1][0] == "settle"


def test_teams_winning_team_splits(client, three_players, split_chain):
    create(client, "teams")
    join(client, "maya", team=0)
    join(client, "sam", team=1)
    join(client, "zoe", team=1)
    workout(client, "sam", distance_km=5)
    body = end_now(client)
    assert sorted(body["winners"]) == sorted([WALLETS["sam"], WALLETS["zoe"]])


def test_a_join_without_a_team_goes_to_the_smaller_team(client, three_players):
    create(client, "teams")
    join(client, "maya", team=0)
    join(client, "sam")  # e.g. our join script, which knows nothing about teams
    join(client, "zoe")
    teams = {p["name"]: p["team"] for p in state(client)["players"]}
    assert teams["sam"] == 1 and teams["zoe"] == 0


def test_too_few_players_still_refund_in_every_format(client, fakes, split_chain):
    create(client, "podium")
    join(client, "maya")
    fakes.players = [WALLETS["maya"]]
    fakes.start_time = int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp())
    body = client.post(f"/challenges/{CHALLENGE}/finish", headers=make_token("maya")).json()
    assert body["action"] == "refunded" and split_chain[-1] == ("refund",)
