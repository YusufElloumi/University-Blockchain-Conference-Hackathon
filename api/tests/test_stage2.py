"""Login token checks, the gas drip, and the once-per-user test funds rule. No network needed."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlalchemy import create_engine

import auth
import config
import db
import main
import treasury

PRIVY_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_KEY = ec.generate_private_key(ec.SECP256R1())
WALLET = "6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD"


def make_token(key=PRIVY_KEY, **overrides):
    claims = {"sub": "did:privy:user1", "iss": "privy.io", "aud": "test-app-id",
              "iat": int(time.time()), "exp": int(time.time()) + 3600, **overrides}
    return jwt.encode(claims, key, algorithm="ES256")


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    """Fake Privy keys, an empty in-memory database, and a fake treasury that records what it sent."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db.SessionLocal, "kw", {**db.SessionLocal.kw, "bind": engine})
    monkeypatch.setattr(auth, "_signing_keys", lambda: [OTHER_KEY.public_key(), PRIVY_KEY.public_key()])
    monkeypatch.setattr(auth, "fetch_privy_user", lambda pid: auth.PrivyUser(pid, "maya@example.com", WALLET))
    sent = {"gas": [], "usdc": [], "sol": 0, "usdc_balance": 0}

    def send_gas(wallet):
        sent["gas"].append(str(wallet))
        sent["sol"] += config.GAS_DRIP_LAMPORTS
        return "gas-signature"

    def send_usdc(wallet):
        sent["usdc"].append(str(wallet))
        sent["usdc_balance"] += config.TEST_FUNDS_UNITS
        return "usdc-signature"

    monkeypatch.setattr(treasury, "send_gas", send_gas)
    monkeypatch.setattr(treasury, "send_usdc", send_usdc)
    monkeypatch.setattr(treasury, "sol_balance", lambda wallet: sent["sol"])
    monkeypatch.setattr(treasury, "usdc_balance", lambda wallet: sent["usdc_balance"])
    return sent


@pytest.fixture
def client():
    return TestClient(main.app)


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_returns_user_id():
    assert auth.verify_access_token(make_token()) == "did:privy:user1"


@pytest.mark.parametrize("token", [
    make_token(key=ec.generate_private_key(ec.SECP256R1())),  # not signed by Privy
    make_token(exp=int(time.time()) - 10),                    # expired
    make_token(iss="evil.example"),                           # wrong issuer
    make_token(aud="another-app"),                            # issued for another app
    jwt.encode({"sub": "x", "iss": "privy.io", "aud": "test-app-id", "exp": int(time.time()) + 60},
               "secret", algorithm="HS256"),                  # wrong algorithm
    "not-a-token",
])
def test_bad_tokens_are_rejected(token):
    with pytest.raises(auth.AuthError):
        auth.verify_access_token(token)


def test_endpoints_need_a_token(client):
    assert client.post("/me/setup").status_code == 401
    assert client.post("/me/fund", headers=bearer("junk")).status_code == 401


def test_setup_drips_gas_once(client, fakes):
    first = client.post("/me/setup", headers=bearer(make_token()))
    assert first.status_code == 200
    assert first.json()["wallet"] == WALLET and first.json()["ready"] is True
    assert fakes["gas"] == [WALLET]
    client.post("/me/setup", headers=bearer(make_token()))  # wallet now has SOL: no second drip
    assert fakes["gas"] == [WALLET]


def test_gas_drip_is_capped_per_user(client, fakes, monkeypatch):
    monkeypatch.setattr(treasury, "sol_balance", lambda wallet: 0)  # wallet keeps getting emptied
    for _ in range(config.GAS_DRIP_MAX_PER_USER):
        assert client.post("/me/setup", headers=bearer(make_token())).json()["ready"] is True
    assert client.post("/me/setup", headers=bearer(make_token())).json()["ready"] is False
    assert len(fakes["gas"]) == config.GAS_DRIP_MAX_PER_USER


def test_test_funds_only_once(client, fakes):
    first = client.post("/me/fund", headers=bearer(make_token()))
    assert first.status_code == 200 and first.json()["usdc"] == 5 and first.json()["test_funds_used"] is True
    assert client.post("/me/fund", headers=bearer(make_token())).status_code == 409
    assert fakes["usdc"] == [WALLET]


def test_failed_transfer_can_be_retried(client, fakes, monkeypatch):
    def boom(wallet):
        raise RuntimeError("rpc down")
    good = treasury.send_usdc
    monkeypatch.setattr(treasury, "send_usdc", boom)
    assert client.post("/me/fund", headers=bearer(make_token())).status_code == 503
    monkeypatch.setattr(treasury, "send_usdc", good)
    assert client.post("/me/fund", headers=bearer(make_token())).status_code == 200


def test_wallet_not_ready_yet(client, monkeypatch):
    monkeypatch.setattr(auth, "fetch_privy_user", lambda pid: auth.PrivyUser(pid, "maya@example.com", None))
    assert client.post("/me/setup", headers=bearer(make_token())).status_code == 409
