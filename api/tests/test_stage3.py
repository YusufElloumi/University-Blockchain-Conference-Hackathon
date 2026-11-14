"""QuickNode webhook: signature check, event decoding, and no duplicates. No network needed."""

import base64
import gzip
import hashlib
import hmac
import json
import struct
import time

import pytest
from fastapi.testclient import TestClient
from solders.pubkey import Pubkey
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

import chain
import config
import db
import events
import main

TOKEN = "test-stream-token"
CHALLENGE = "GNLFdSczFf1GgYXwF1nPLwzTL4Jz5QJrknAMS67vDDc"
PLAYER = "6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD"


def disc(name):
    return bytes(next(e["discriminator"] for e in chain.IDL["events"] if e["name"] == name))


def joined_log(count=1, pool=1_000_000):
    raw = disc("PlayerJoined") + bytes(Pubkey.from_string(CHALLENGE)) + bytes(Pubkey.from_string(PLAYER))
    raw += struct.pack("<BQ", count, pool)
    return "Program data: " + base64.b64encode(raw).decode()


def settled_log():
    raw = disc("ChallengeSettled") + bytes(Pubkey.from_string(CHALLENGE))
    raw += struct.pack("<I", 1) + bytes(Pubkey.from_string(PLAYER)) + struct.pack("<QQ", 2_000_000, 2_000_000)
    raw += bytes(range(32))
    return "Program data: " + base64.b64encode(raw).decode()


def delivery(logs, signature="sig1"):
    return {
        "data": {"transactions": [{"signature": signature, "slot": 5, "blockTime": 1794700000, "logs": logs}]},
        "metadata": {"network": "solana-devnet"},
    }


def signed(body: bytes, token=TOKEN, timestamp=None):
    nonce, timestamp = "abc123", timestamp or str(int(time.time()))
    signature = hmac.new(token.encode(), nonce.encode() + timestamp.encode() + body, hashlib.sha256).hexdigest()
    return {
        "X-QN-Nonce": nonce,
        "X-QN-Timestamp": timestamp,
        "X-QN-Signature": signature,
        "Content-Type": "application/json",
    }


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(db.SessionLocal, "kw", {**db.SessionLocal.kw, "bind": engine})
    monkeypatch.setattr(config, "QUICKNODE_STREAM_SECURITY_TOKEN", TOKEN)
    return TestClient(main.app)


def post(client, payload, **kw):
    body = json.dumps(payload).encode()
    return client.post("/webhooks/quicknode", content=body, headers=signed(body, **kw))


def test_decodes_events():
    name, fields = events.decode_events(["Program log: hi", joined_log(2, 2_000_000)])[0]
    assert name == "PlayerJoined"
    assert fields == {"challenge": CHALLENGE, "player": PLAYER, "player_count": 2, "pool_total": 2_000_000}
    name, fields = events.decode_events([settled_log()])[0]
    assert name == "ChallengeSettled" and fields["winners"] == [PLAYER] and fields["payout_each"] == 2_000_000
    assert fields["score_hash"] == bytes(range(32)).hex()


def test_every_event_field_type_in_the_idl_is_supported():
    for event in chain.IDL["events"]:
        for field in events._TYPES[event["name"]]["fields"]:
            events._read(bytes(200), 0, field["type"])


def test_ignores_other_programs_and_junk():
    other = "Program data: " + base64.b64encode(b"\x01" * 40).decode()
    assert events.decode_events([other, "Program data: !!!", "Program data: ", None]) == []


def test_stores_event_and_serves_it(client):
    response = post(client, delivery(["Program log: Instruction: JoinChallenge", joined_log()]))
    assert response.status_code == 200 and response.json()["new_events"] == 1
    feed = client.get(f"/challenges/{CHALLENGE}/events").json()
    assert feed[0]["name"] == "PlayerJoined" and feed[0]["data"]["player"] == PLAYER
    assert feed[0]["signature"] == "sig1"


def test_same_delivery_twice_is_stored_once(client):
    payload = delivery([joined_log()])
    assert post(client, payload).json()["new_events"] == 1
    assert post(client, payload).json()["new_events"] == 0
    assert len(client.get(f"/challenges/{CHALLENGE}/events").json()) == 1


def test_unwrapped_and_gzipped_bodies_work(client):
    unwrapped = delivery([joined_log()], "sig-plain")["data"]
    assert post(client, unwrapped).json()["new_events"] == 1
    body = json.dumps(delivery([joined_log()], "sig-gzip")).encode()
    response = client.post(
        "/webhooks/quicknode", content=gzip.compress(body), headers={**signed(body), "Content-Encoding": "gzip"}
    )
    assert response.status_code == 200 and response.json()["new_events"] == 1


def test_rejects_unsigned_wrong_token_tampered_and_old(client):
    body = json.dumps(delivery([joined_log()])).encode()
    assert client.post("/webhooks/quicknode", content=body).status_code == 401
    assert client.post("/webhooks/quicknode", content=body, headers=signed(body, token="wrong")).status_code == 401
    assert client.post("/webhooks/quicknode", content=body + b" ", headers=signed(body)).status_code == 401
    old = str(int(time.time()) - 3600)
    assert client.post("/webhooks/quicknode", content=body, headers=signed(body, timestamp=old)).status_code == 401
    assert client.get(f"/challenges/{CHALLENGE}/events").json() == []


def test_empty_delivery_is_accepted(client):
    assert post(client, {"data": None, "metadata": {}}).json()["new_events"] == 0
