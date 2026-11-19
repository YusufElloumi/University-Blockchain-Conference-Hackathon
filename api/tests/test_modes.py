"""Play modes (league, public, private) and their access rules. No network needed."""

from datetime import datetime, timedelta, timezone

import pytest

import db
from test_stage4 import CHALLENGE, client, fakes, make_token  # noqa: F401

PRIVATE = "Priv111111111111111111111111111111111111111"
LEAGUE = "Leag111111111111111111111111111111111111111"
PUBLIC = "Publ111111111111111111111111111111111111111"


@pytest.fixture
def joining(fakes):
    """The pretend onchain challenge is still open for joining (kick-off in an hour)."""
    now = datetime.now(timezone.utc)
    fakes.start_time = int((now + timedelta(hours=1)).timestamp())
    fakes.end_time = int((now + timedelta(days=7)).timestamp())
    return fakes


def create(client, address, mode, **extra):
    reply = client.post("/challenges", json={"address": address, "name": f"{mode} week", "mode": mode, **extra},
                        headers=make_token("maya"))
    assert reply.status_code == 200, reply.text
    return reply.json()


def join(client, address, who="sam"):
    return client.post(f"/challenges/{address}/join", json={"consent": True}, headers=make_token(who))


def redeem(client, code, who="sam"):
    return client.post("/invites/redeem", json={"code": code}, headers=make_token(who))


def test_mode_is_recorded_and_shown(client):
    body = create(client, PRIVATE, "private")
    assert body["mode"] == "private" and body["organizer_name"] is None
    assert len(body["invite_code"]) == 6 and body["invite_code"].isupper()


def test_a_league_needs_an_organizer_name(client):
    reply = client.post("/challenges", json={"address": LEAGUE, "name": "Gym week", "mode": "league"},
                        headers=make_token("maya"))
    assert reply.status_code == 400
    body = create(client, LEAGUE, "league", organizer_name="  Iron   Temple Gym ")
    assert body["organizer_name"] == "Iron Temple Gym"


def test_organizer_name_is_dropped_outside_leagues(client):
    assert create(client, PUBLIC, "public", organizer_name="Nobody")["organizer_name"] is None


def test_only_public_events_are_listed(client, joining):
    create(client, PUBLIC, "public")
    create(client, PRIVATE, "private")
    create(client, LEAGUE, "league", organizer_name="Club")
    listed = client.get("/events/public", headers=make_token("zoe")).json()
    assert [e["address"] for e in listed] == [PUBLIC]
    assert listed[0]["player_count"] == 0 and listed[0]["max_players"] == 8


def test_public_list_hides_events_whose_joining_has_closed(client, fakes):
    create(client, PUBLIC, "public")  # the default fake started two days ago
    assert client.get("/events/public", headers=make_token("zoe")).json() == []


@pytest.mark.parametrize("mode,extra", [("private", {}), ("league", {"organizer_name": "Club"})])
def test_invite_only_events_cannot_be_read_or_joined_without_a_code(client, joining, mode, extra):
    address = PRIVATE if mode == "private" else LEAGUE
    create(client, address, mode, **extra)
    sam = make_token("sam")
    assert client.get(f"/challenges/{address}/state", headers=sam).status_code == 404
    assert client.get(f"/challenges/{address}/leaderboard", headers=sam).status_code == 404
    assert client.get(f"/challenges/{address}/score-sheet", headers=sam).status_code == 404
    assert client.post(f"/challenges/{address}/finish", headers=sam).status_code == 404
    assert join(client, address).status_code == 404
    assert client.get("/me/challenges", headers=sam).json() == []
    with db.SessionLocal() as session:
        assert session.query(db.Participant).count() == 0


@pytest.mark.parametrize("mode,extra", [("private", {}), ("league", {"organizer_name": "Club"})])
def test_a_wrong_code_is_rejected_and_a_right_one_lets_a_second_account_join(client, joining, mode, extra):
    address = PRIVATE if mode == "private" else LEAGUE
    code = create(client, address, mode, **extra)["invite_code"]
    assert redeem(client, "WRONG1").status_code == 404
    assert client.get(f"/challenges/{address}/state", headers=make_token("sam")).status_code == 404

    reply = redeem(client, code.lower())  # codes are not case sensitive
    assert reply.status_code == 200 and reply.json()["address"] == address
    assert redeem(client, code).status_code == 200  # safe to repeat
    assert client.get(f"/challenges/{address}/state", headers=make_token("sam")).status_code == 200
    invited = client.get(f"/me/challenges?mode={mode}", headers=make_token("sam")).json()
    assert [(c["address"], c["joined"]) for c in invited] == [(address, False)]

    assert join(client, address).status_code == 200
    assert client.get(f"/me/challenges?mode={mode}", headers=make_token("sam")).json()[0]["joined"] is True
    assert client.get("/me/challenges?mode=public", headers=make_token("sam")).json() == []


def test_the_creator_of_a_private_game_can_join_without_a_code(client, joining):
    create(client, PRIVATE, "private")
    assert join(client, PRIVATE, "maya").status_code == 200


def test_a_league_organizer_sees_the_event_without_playing(client, joining):
    create(client, LEAGUE, "league", organizer_name="Club")
    body = client.get(f"/challenges/{LEAGUE}/state", headers=make_token("maya")).json()
    assert body["you"]["is_creator"] and not body["you"]["joined"]
    assert body["challenge"]["organizer_name"] == "Club"


def test_anyone_can_read_and_join_a_public_event(client, joining):
    create(client, PUBLIC, "public")
    assert client.get(f"/challenges/{PUBLIC}/state", headers=make_token("sam")).status_code == 200
    assert join(client, PUBLIC).status_code == 200


def test_events_from_before_play_modes_count_as_private(client):
    with db.SessionLocal() as session:
        session.add(db.Challenge(
            address=PRIVATE, name="Old week", buy_in_units=1, start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc), invite_code="old-Code_1", mode=None,
        ))
        session.commit()
    db.init_db()
    with db.SessionLocal() as session:
        assert session.query(db.Challenge).one().mode == "private"
    assert client.get(f"/challenges/{PRIVATE}/state", headers=make_token("sam")).status_code == 404
    assert redeem(client, "old-Code_1").status_code == 200  # older mixed-case codes still work
    assert client.get(f"/challenges/{PRIVATE}/state", headers=make_token("sam")).json()["challenge"]["mode"] == "private"


def test_an_event_made_outside_the_app_is_recorded_as_public(client):
    assert join(client, CHALLENGE).status_code == 200
    assert client.get(f"/challenges/{CHALLENGE}/state", headers=make_token("zoe")).json()["challenge"]["mode"] == "public"


@pytest.mark.parametrize("mode,extra", [("private", {}), ("league", {"organizer_name": "Club"})])
def test_rival_admins_can_open_any_event(client, joining, monkeypatch, mode, extra):
    """Admins (ADMIN_EMAILS) can open invite-only events to run demos; the legal pages say so."""
    import config
    address = PRIVATE if mode == "private" else LEAGUE
    create(client, address, mode, **extra)
    assert client.get(f"/challenges/{address}/state", headers=make_token("sam")).status_code == 404
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"sam@example.com"})
    assert client.get(f"/challenges/{address}/state", headers=make_token("sam")).status_code == 200
    # Points were shared with the group only, so an admin who is not playing still cannot read the leaderboard.
    assert client.get(f"/challenges/{address}/state", headers=make_token("sam")).json()["players"] is None
    assert client.get(f"/challenges/{address}/leaderboard", headers=make_token("sam")).status_code == 403
