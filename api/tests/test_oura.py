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

    def post(self, url, data=None, headers=None, timeout=None):
        assert url == oura.TOKEN_URL and headers.get("User-Agent")
        self.posts.append(dict(data))
        if self.token_status != 200:
            return Reply(self.token_status, {"error": "invalid_grant"})
        n, self.serial = self.serial, self.serial + 1
        return Reply(200, {"token_type": "bearer", "access_token": f"oura-access-SECRET-{n}",
                           "refresh_token": f"oura-refresh-SECRET-{n}", "expires_in": 86400})

    def get(self, url, params=None, headers=None, timeout=None):
        assert url == oura.REVOKE_URL
        self.revoked.append(params["access_token"])
        return Reply(self.revoke_status)


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
