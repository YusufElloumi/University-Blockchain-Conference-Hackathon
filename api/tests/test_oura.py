"""Oura connection (OAuth with PKCE): start, callback, complete, refresh, disconnect. Oura itself is faked; no network."""

import base64
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

import auth
import config
import db
import main
import secretbox
from fitness import oura

PRIVY_KEY = ec.generate_private_key(ec.SECP256R1())
WALLETS = {"maya": "6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD", "sam": "J73KdqANTzJ7P1TMTnd37xNCdXvc3LChG7J8X1XX4XY9"}
WEB = "https://rival-app.ca"
ACCESS, REFRESH = "oura-access-SECRET-1", "oura-refresh-SECRET-1"


def login(who="maya"):
    claims = {"sub": f"did:privy:{who}", "iss": "privy.io", "aud": "test-app-id",
              "iat": int(time.time()), "exp": int(time.time()) + 3600}
    return {"Authorization": "Bearer " + jwt.encode(claims, PRIVY_KEY, algorithm="ES256")}


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self._body = status, body or {}

    def json(self):
        return self._body


class FakeOura:
    """Stands in for Oura's token and revoke endpoints and records what was sent."""

    def __init__(self):
        self.posts, self.revoked = [], []
        self.token_status = 200
        self.revoke_status = 200
        self.serial = 1
        self.scope = None  # what Oura's token reply says was granted (None: no "scope" field)
        self.data_calls, self.data_status, self.pages = [], {}, {}

    def post(self, url, data=None, headers=None, timeout=None):
        assert url == oura.TOKEN_URL and headers.get("User-Agent")
        self.posts.append(dict(data))
        if self.token_status != 200:
            return Reply(self.token_status, {"error": "invalid_grant"})
        n, self.serial = self.serial, self.serial + 1
        body = {"token_type": "bearer", "access_token": f"oura-access-SECRET-{n}",
                "refresh_token": f"oura-refresh-SECRET-{n}", "expires_in": 86400}
        if self.scope is not None:
            body["scope"] = self.scope
        return Reply(200, body)

    def get(self, url, params=None, headers=None, timeout=None):
        if url == oura.REVOKE_URL:
            self.revoked.append(params["access_token"])
            return Reply(self.revoke_status)
        # Oura's data API (synthetic records only; see the data tests below).
        assert headers.get("User-Agent") and headers["Authorization"].startswith("Bearer ")
        self.data_calls.append((url, dict(params), headers["Authorization"][7:]))
        status = self.data_status.get(url, 200)
        if status != 200:
            return Reply(status, {"detail": "synthetic error SECRET-DETAIL"})
        pages = self.pages.get(url, [[]])
        page = int((params or {}).get("next_token") or 0)
        rows = pages[page]
        if url.endswith("/heartrate"):  # only samples inside the asked-for window, like the real API
            lo, hi = params["start_datetime"], params["end_datetime"]
            rows = [r for r in rows if lo <= r["timestamp"] <= hi]
        return Reply(200, {"data": rows, "next_token": str(page + 1) if page + 1 < len(pages) else None})


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db.SessionLocal, "kw", {**db.SessionLocal.kw, "bind": engine})
    monkeypatch.setattr(auth, "_signing_keys", lambda: [PRIVY_KEY.public_key()])
    monkeypatch.setattr(auth, "fetch_privy_user",
                        lambda pid: auth.PrivyUser(pid, "x@example.com", WALLETS[pid.split(":")[-1]]))
    monkeypatch.setattr(config, "WEB_ORIGINS", [WEB, "http://localhost:5173"])
    monkeypatch.setattr(config, "OURA_CLIENT_ID", "client-123")
    monkeypatch.setattr(config, "OURA_CLIENT_SECRET", "client-secret-xyz")
    monkeypatch.setattr(config, "OURA_REDIRECT_URI", "https://loser-buys-api.onrender.com/integrations/oura/callback")
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    fake = FakeOura()
    monkeypatch.setattr(oura.httpx, "post", fake.post)
    monkeypatch.setattr(oura.httpx, "get", fake.get)
    return fake


@pytest.fixture
def client():
    return TestClient(main.app, follow_redirects=False)


def start(client, who="maya"):
    reply = client.post("/integrations/oura/start", json={"return_to": WEB + "/"}, headers=login(who))
    assert reply.status_code == 200, reply.text
    return parse_qs(urlsplit(reply.json()["url"]).query)


def come_back(client, state, **extra):
    reply = client.get("/integrations/oura/callback", params={"state": state, **extra})
    assert reply.status_code == 303
    target = urlsplit(reply.headers["location"])
    return f"{target.scheme}://{target.netloc}{target.path}", {k: v[0] for k, v in parse_qs(target.query).items()}


def connect(client, who="maya"):
    state = start(client, who)["state"][0]
    _, params = come_back(client, state, code="one-time-code")
    reply = client.post("/integrations/oura/complete", json={"state": params["oura_state"]}, headers=login(who))
    assert reply.status_code == 200, reply.text
    return reply


def stored(who_id=1):
    with db.SessionLocal() as s:
        return s.scalar(select(db.FitnessConnection).where(db.FitnessConnection.user_id == who_id))


# ---------- start ----------


def test_start_asks_only_for_workout_and_heartrate_with_pkce(client):
    query = start(client)
    assert query["scope"] == ["workout heartrate"]
    assert query["response_type"] == ["code"] and query["client_id"] == ["client-123"]
    assert query["redirect_uri"] == [config.OURA_REDIRECT_URI]
    assert query["code_challenge_method"] == ["S256"] and len(query["state"][0]) >= 40
    with db.SessionLocal() as s:
        row = s.scalar(select(db.OAuthState))
        assert row.state_hash != query["state"][0]  # only the hash is stored
        verifier = secretbox.decrypt(row.code_verifier_enc)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert query["code_challenge"] == [challenge]


def test_start_needs_login_and_a_known_return_address(client):
    assert client.post("/integrations/oura/start", json={"return_to": WEB}).status_code == 401
    for bad in ("https://evil.example/", "javascript:alert(1)", "https://rival-app.ca.evil.example/"):
        assert client.post("/integrations/oura/start", json={"return_to": bad}, headers=login()).status_code == 400


def test_unavailable_when_not_configured(client, monkeypatch):
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", "")
    assert client.get("/integrations/oura", headers=login()).json()["available"] is False
    assert client.post("/integrations/oura/start", json={"return_to": WEB}, headers=login()).status_code == 503
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "OURA_CLIENT_SECRET", "")
    assert client.post("/integrations/oura/start", json={"return_to": WEB}, headers=login()).status_code == 503


# ---------- the full flow ----------


def test_connect_end_to_end_with_a_fake_oura(client, setup):
    state = start(client)["state"][0]
    page, params = come_back(client, state, code="one-time-code")
    assert page == WEB + "/" and params == {"oura": "finish", "oura_state": state}
    assert client.get("/integrations/oura", headers=login()).json()["connected"] is False  # not until complete

    reply = client.post("/integrations/oura/complete", json={"state": state}, headers=login())
    assert reply.status_code == 200
    assert reply.json()["connected"] is True and reply.json()["missing_permissions"] == []
    sent = setup.posts[0]
    assert sent["grant_type"] == "authorization_code" and sent["code"] == "one-time-code"
    assert sent["client_secret"] == "client-secret-xyz" and sent["redirect_uri"] == config.OURA_REDIRECT_URI
    assert len(sent["code_verifier"]) >= 43

    row = stored()
    assert row.provider == "oura"
    assert ACCESS not in row.access_token_enc and REFRESH not in row.refresh_token_enc  # encrypted
    assert secretbox.decrypt(row.access_token_enc) == ACCESS
    with db.SessionLocal() as s:  # the code and PKCE secret are wiped once used
        attempt = s.scalar(select(db.OAuthState))
        assert attempt.code_enc is None and attempt.code_verifier_enc is None and attempt.used_at


def test_tokens_never_reach_the_browser_or_the_logs(client, caplog):
    caplog.set_level(logging.DEBUG)
    replies = [connect(client).text, client.get("/integrations/oura", headers=login()).text,
               client.delete("/integrations/oura", headers=login()).text]
    for text in replies + [caplog.text]:
        assert "SECRET" not in text and "client-secret-xyz" not in text and "one-time-code" not in text


# ---------- binding, single use, expiry, cancel ----------


def test_only_the_account_that_started_can_finish(client):
    state = start(client, "maya")["state"][0]
    come_back(client, state, code="one-time-code")
    reply = client.post("/integrations/oura/complete", json={"state": state}, headers=login("sam"))
    assert reply.status_code == 403
    # The attempt is burned, so the code can't be used by anyone afterwards either.
    assert client.post("/integrations/oura/complete", json={"state": state}, headers=login("maya")).status_code == 409
    assert stored(1) is None and stored(2) is None


def test_each_attempt_works_once(client):
    state = start(client)["state"][0]
    come_back(client, state, code="one-time-code")
    _, again = come_back(client, state, code="another-code")
    assert again == {"oura": "error", "reason": "expired"}
    assert client.post("/integrations/oura/complete", json={"state": state}, headers=login()).status_code == 200
    assert client.post("/integrations/oura/complete", json={"state": state}, headers=login()).status_code == 409


def test_expired_attempts_are_refused(client):
    state = start(client)["state"][0]
    with db.SessionLocal() as s:
        s.scalar(select(db.OAuthState)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.commit()
    _, params = come_back(client, state, code="one-time-code")
    assert params == {"oura": "error", "reason": "expired"}


def test_expiry_also_applies_between_callback_and_complete(client):
    state = start(client)["state"][0]
    come_back(client, state, code="one-time-code")
    with db.SessionLocal() as s:
        s.scalar(select(db.OAuthState)).expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        s.commit()
    assert client.post("/integrations/oura/complete", json={"state": state}, headers=login()).status_code == 410


def test_cancelled_and_unknown_attempts(client):
    state = start(client)["state"][0]
    page, params = come_back(client, state, error="access_denied")
    assert page == WEB + "/" and params == {"oura": "cancelled"}
    assert client.post("/integrations/oura/complete", json={"state": state}, headers=login()).status_code == 409
    _, params = come_back(client, "x" * 43, code="c")
    assert params == {"oura": "error", "reason": "unknown"}
    reply = client.get("/integrations/oura/callback")
    assert parse_qs(urlsplit(reply.headers["location"]).query)["oura"] == ["error"]


def test_refused_code_exchange_connects_nothing(client, setup):
    setup.token_status = 400
    state = start(client)["state"][0]
    come_back(client, state, code="bad")
    assert client.post("/integrations/oura/complete", json={"state": state}, headers=login()).status_code == 400
    assert stored() is None


def test_starting_again_replaces_an_unfinished_attempt(client):
    first = start(client)["state"][0]
    start(client)
    _, params = come_back(client, first, code="c")
    assert params["reason"] == "unknown"


# ---------- refresh ----------


def expire_token():
    with db.SessionLocal() as s:
        row = s.scalar(select(db.FitnessConnection))
        row.token_expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
        s.commit()


def test_refresh_swaps_in_the_new_single_use_refresh_token(client, setup):
    connect(client)
    with db.SessionLocal() as s:
        assert oura.access_token(s, 1) == ACCESS  # still fresh: no refresh
    expire_token()
    with db.SessionLocal() as s:
        assert oura.access_token(s, 1) == "oura-access-SECRET-2"
    assert setup.posts[-1] == {"grant_type": "refresh_token", "refresh_token": REFRESH,
                               "client_id": "client-123", "client_secret": "client-secret-xyz"}
    assert secretbox.decrypt(stored().refresh_token_enc) == "oura-refresh-SECRET-2"


def test_a_refused_refresh_forgets_the_dead_link(client, setup):
    connect(client)
    expire_token()
    setup.token_status = 400
    with db.SessionLocal() as s, pytest.raises(oura.OuraError) as e:
        oura.access_token(s, 1)
    assert e.value.status == 401 and stored() is None


# ---------- disconnect ----------


def test_disconnect_revokes_and_deletes(client, setup):
    connect(client)
    reply = client.delete("/integrations/oura", headers=login())
    assert reply.json() == {"available": True, "connected": False, "connected_at": None,
                            "missing_permissions": [], "revoked": True}
    assert setup.revoked == [ACCESS] and stored() is None


def test_disconnect_deletes_even_if_oura_does_not_answer(client, setup):
    connect(client)
    setup.revoke_status = 500
    assert client.delete("/integrations/oura", headers=login()).json()["revoked"] is False
    assert stored() is None


def test_one_users_disconnect_leaves_others_alone(client):
    connect(client, "maya")
    connect(client, "sam")
    client.delete("/integrations/oura", headers=login("maya"))
    assert stored(1) is None and stored(2) is not None


def test_request_log_hides_the_callback_code():
    record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                               ("1.2.3.4:5", "GET", "/integrations/oura/callback?code=abc&state=xyz", "1.1", 303), None)
    main._HideOAuthQuery().filter(record)
    assert "abc" not in record.getMessage() and "xyz" not in record.getMessage()


# ---------- granted permissions ----------


@pytest.mark.parametrize("granted, missing", [
    ("extapi:workout extapi:heartrate", []),  # Oura's newer sign-in server (seen on the live app)
    ("workout heartrate", []),  # the older format
    ("openid extapi:heartrate extapi:workout email", []),  # extras and any order
    ("extapi:workout,extapi:heartrate", []),  # comma-separated
    ("extapi:workout", ["heartrate"]),  # really missing one
    ("extapi:daily", ["workout", "heartrate"]),
    ("heartrate_extra xworkout", ["workout", "heartrate"]),  # near-misses don't count
])
def test_permissions_are_compared_by_plain_name(client, setup, granted, missing):
    setup.scope = granted
    assert connect(client).json()["missing_permissions"] == missing
    assert stored().scopes == granted  # stored exactly as Oura sent it



# ---------- read-only workout check (synthetic data only) ----------

from fitness import oura_data  # noqa: E402

WORKOUT_A = {  # a full record, every documented field, plus one Oura might add later
    "id": "wk-synthetic-a", "activity": "running", "calories": 412.5, "day": "2026-11-17",
    "distance": 8123.0, "start_datetime": "2026-11-17T07:00:00-06:00", "end_datetime": "2026-11-17T07:40:00-06:00",
    "intensity": "hard", "label": None, "source": "autodetected", "extra_field": "SYNTHETIC-VALUE",
}
WORKOUT_B = {  # a sparse record: optional fields missing or empty
    "id": "wk-synthetic-b", "activity": "strengthTraining", "day": "2026-11-15",
    "start_datetime": "2026-11-15T18:00:00-06:00", "end_datetime": "2026-11-15T18:30:00-06:00",
    "intensity": "moderate", "source": "manual", "calories": None,
}


def hr(ts, bpm=150, source="workout"):
    return {"timestamp": ts, "timestamp_unix": 0, "bpm": bpm, "source": source}


# Workout A runs 13:00-13:40 UTC: samples every 5 minutes for the first 20 minutes, then nothing.
HR_A = [hr(f"2026-11-17T13:{m:02d}:00+00:00", bpm=171) for m in range(0, 20, 5)] + [hr("2026-11-17T12:30:00+00:00", 63, "awake")]


def readings(client, **params):
    return client.get("/integrations/oura/workouts", params=params, headers=login())


def test_workouts_need_login_and_a_connection(client):
    assert client.get("/integrations/oura/workouts").status_code == 401
    assert readings(client).status_code == 404  # signed in, but Oura isn't connected


def test_workout_fields_and_heart_rate_coverage(client, setup):
    connect(client)
    setup.pages = {oura_data.WORKOUT_URL: [[WORKOUT_B], [WORKOUT_A]], oura_data.HEARTRATE_URL: [HR_A]}
    reply = readings(client, days=7, limit=5)
    assert reply.status_code == 200 and reply.headers["cache-control"] == "no-store, private"
    body = reply.json()
    assert body["workouts_found"] == 2 and [w["id"] for w in body["workouts"]] == ["wk-synthetic-a", "wk-synthetic-b"]

    a, b = body["workouts"]
    assert a["duration_minutes"] == 40.0 and a["distance_km"] == 8.123 and a["calories"] == 412.5
    assert a["missing_fields"] == ["label"] and a["undocumented_fields"] == ["extra_field"]
    assert b["missing_fields"] == ["calories", "distance", "label"]
    assert body["field_presence"]["distance"] == 1 and body["field_presence"]["id"] == 2

    assert a["heart_rate"] == {"status": "ok", "sample_count": 4, "workout_minutes": 40, "minutes_with_samples": 4,
                               "coverage_pct": 10.0, "sources": {"workout": 4}, "median_gap_seconds": 300.0,
                               "first_sample_after_start_seconds": 0, "last_sample_before_end_seconds": 1500}
    assert b["heart_rate"]["sample_count"] == 0 and b["heart_rate"]["coverage_pct"] == 0.0

    text = reply.text  # counts only: no bpm values, and no values of undocumented fields
    assert "171" not in text and '"bpm"' not in text and "SYNTHETIC-VALUE" not in text


def test_workout_check_asks_oura_for_the_right_window_with_the_users_token(client, setup):
    connect(client)
    setup.pages = {oura_data.WORKOUT_URL: [[WORKOUT_A]], oura_data.HEARTRATE_URL: [HR_A]}
    readings(client, days=14)
    url, params, token = setup.data_calls[0]
    assert url == "https://api.ouraring.com/v2/usercollection/workout" and token == ACCESS
    assert set(params) == {"start_date", "end_date"}
    url, params, _ = setup.data_calls[-1]
    assert url == "https://api.ouraring.com/v2/usercollection/heartrate"
    assert params == {"start_datetime": "2026-11-17T13:00:00+00:00", "end_datetime": "2026-11-17T13:40:00+00:00"}


def test_workout_check_refreshes_an_expiring_token_first(client, setup):
    connect(client)
    expire_token()
    setup.pages = {oura_data.WORKOUT_URL: [[]]}
    assert readings(client).status_code == 200
    assert setup.data_calls[0][2] == "oura-access-SECRET-2"


def test_limit_and_parameter_bounds(client, setup):
    connect(client)
    many = [{**WORKOUT_B, "id": f"wk-{i}", "start_datetime": f"2026-11-{i + 1:02d}T18:00:00-06:00",
             "end_datetime": f"2026-11-{i + 1:02d}T18:30:00-06:00"} for i in range(12)]
    setup.pages = {oura_data.WORKOUT_URL: [many], oura_data.HEARTRATE_URL: [[]]}
    body = readings(client, limit=3).json()
    assert body["workouts_found"] == 12 and [w["id"] for w in body["workouts"]] == ["wk-11", "wk-10", "wk-9"]
    for bad in ({"days": 0}, {"days": 91}, {"limit": 0}, {"limit": 26}):
        assert readings(client, **bad).status_code == 422


def test_missing_heart_rate_permission_is_reported_not_fatal(client, setup):
    connect(client)
    setup.pages = {oura_data.WORKOUT_URL: [[WORKOUT_A, WORKOUT_B]]}
    setup.data_status = {oura_data.HEARTRATE_URL: 403}
    body = readings(client).json()
    assert [w["heart_rate"]["status"] for w in body["workouts"]] == ["unavailable", "unavailable"]
    assert sum(1 for c in setup.data_calls if c[0] == oura_data.HEARTRATE_URL) == 1  # asked once, not per workout


@pytest.mark.parametrize("status, expected", [(401, 401), (403, 403), (429, 429), (500, 502)])
def test_oura_errors_become_plain_messages(client, setup, status, expected):
    connect(client)
    setup.data_status = {oura_data.WORKOUT_URL: status}
    reply = readings(client)
    assert reply.status_code == expected and "SECRET" not in reply.text


def test_workout_check_stores_nothing_and_logs_no_health_data(client, setup, caplog):
    connect(client)
    caplog.set_level(logging.DEBUG)
    setup.pages = {oura_data.WORKOUT_URL: [[WORKOUT_A]], oura_data.HEARTRATE_URL: [HR_A]}
    with db.SessionLocal() as s:
        before = {t: s.execute(db.Base.metadata.tables[t].select()).all() for t in db.Base.metadata.tables}
    readings(client)
    setup.data_status = {oura_data.WORKOUT_URL: 500}
    readings(client)
    with db.SessionLocal() as s:
        after = {t: s.execute(db.Base.metadata.tables[t].select()).all() for t in db.Base.metadata.tables}
    assert after == before
    for secret in ("wk-synthetic-a", "running", "171", "8123", "SECRET", "SYNTHETIC-VALUE"):
        assert secret not in caplog.text


def test_one_user_cannot_read_anothers_workouts(client, setup):
    connect(client, "maya")
    setup.pages = {oura_data.WORKOUT_URL: [[WORKOUT_A]], oura_data.HEARTRATE_URL: [HR_A]}
    assert client.get("/integrations/oura/workouts", headers=login("sam")).status_code == 404
    assert not setup.data_calls  # Sam isn't connected, so Oura is never called with anyone's token
