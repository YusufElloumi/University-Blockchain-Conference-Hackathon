"""Receives onchain events from the QuickNode Stream and stores them.

The Stream watches Solana devnet, keeps transactions that called our program (streams/filter.js),
and POSTs them to /webhooks/quicknode. Here we:
  1. check the delivery really came from QuickNode (HMAC signature made with the Stream's security token)
  2. decode the program's events from the transaction log lines
  3. store them, skipping any we already have (QuickNode may deliver the same block twice)
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import hmac
import json
import struct
import time
from datetime import datetime, timezone

from solders.pubkey import Pubkey
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import chain
import db

MAX_CLOCK_DRIFT_SECONDS = 600
_EVENTS = {bytes(e["discriminator"]): e["name"] for e in chain.IDL.get("events", [])}
_TYPES = {t["name"]: t["type"] for t in chain.IDL.get("types", [])}


class BadSignature(Exception):
    pass


def verify_delivery(token: str, body: bytes, nonce: str | None, timestamp: str | None, signature: str | None) -> None:
    """Raises BadSignature unless the delivery was signed with our Stream's security token.

    QuickNode signs HMAC-SHA256(token, nonce + timestamp + body) and sends it as hex.
    """
    if not (nonce and timestamp and signature):
        raise BadSignature("Missing signature headers")
    expected = hmac.new(token.encode(), nonce.encode() + timestamp.encode() + body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.strip().lower()):
        raise BadSignature("Signature does not match")
    # Refuse old deliveries, so a captured request cannot be replayed later.
    try:
        sent = float(timestamp)
        sent = sent / 1000 if sent > 1e12 else sent
    except ValueError:
        return
    if abs(time.time() - sent) > MAX_CLOCK_DRIFT_SECONDS:
        raise BadSignature("Delivery is too old")


def decode_body(raw: bytes, content_encoding: str | None) -> bytes:
    """QuickNode can gzip the body; the signature is over the uncompressed JSON."""
    if (content_encoding or "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    return raw


def _read(data: bytes, pos: int, kind) -> tuple[object, int]:
    """Reads one value of an IDL type from Anchor's binary event format (Borsh). Returns (value, new position)."""
    if kind == "pubkey":
        return str(Pubkey.from_bytes(data[pos : pos + 32])), pos + 32
    if kind == "u8":
        return data[pos], pos + 1
    if kind == "u64":
        return struct.unpack_from("<Q", data, pos)[0], pos + 8
    if kind == "i64":
        return struct.unpack_from("<q", data, pos)[0], pos + 8
    if isinstance(kind, dict) and "vec" in kind:
        (count,) = struct.unpack_from("<I", data, pos)
        pos += 4
        items = []
        for _ in range(count):
            item, pos = _read(data, pos, kind["vec"])
            items.append(item)
        return items, pos
    if isinstance(kind, dict) and "array" in kind:
        inner, count = kind["array"]
        if inner == "u8":
            return data[pos : pos + count].hex(), pos + count
        items = []
        for _ in range(count):
            item, pos = _read(data, pos, inner)
            items.append(item)
        return items, pos
    raise ValueError(f"Unsupported event field type: {kind}")


def decode_events(logs: list[str]) -> list[tuple[str, dict]]:
    """Finds our program's events in a transaction's log lines. Returns [(event name, fields), ...]."""
    found = []
    for line in logs:
        if not isinstance(line, str) or not line.startswith("Program data: "):
            continue
        try:
            raw = base64.b64decode(line[len("Program data: ") :])
        except ValueError:
            continue
        name = _EVENTS.get(raw[:8])
        if name is None:
            continue  # an event from some other program in the same transaction
        fields, pos = {}, 8
        try:
            for field in _TYPES[name]["fields"]:
                fields[field["name"]], pos = _read(raw, pos, field["type"])
        except (struct.error, IndexError, ValueError):
            continue
        found.append((name, fields))
    return found


def _transactions(payload) -> list[dict]:
    """Pulls the transaction list out of a delivery, whether or not QuickNode wrapped it in {"data": ...}."""
    if isinstance(payload, dict):
        if isinstance(payload.get("transactions"), list):
            return [t for t in payload["transactions"] if isinstance(t, dict)]
        if "data" in payload:
            return _transactions(payload["data"])
        return []
    if isinstance(payload, list):
        return [t for item in payload for t in _transactions(item)]
    return []


def store_delivery(session: Session, payload) -> int:
    """Stores every new event in a delivery. Safe to run twice on the same data. Returns how many were new."""
    new = 0
    for tx in _transactions(payload):
        signature = tx.get("signature")
        if not signature:
            continue
        block_time = tx.get("blockTime")
        for index, (name, fields) in enumerate(decode_events(tx.get("logs") or [])):
            already = session.scalar(
                select(db.ChainEvent.id).where(
                    db.ChainEvent.signature == signature, db.ChainEvent.event_index == index
                )
            )
            if already is not None:
                continue
            session.add(
                db.ChainEvent(
                    signature=signature,
                    event_index=index,
                    name=name,
                    challenge=fields.get("challenge"),
                    slot=tx.get("slot"),
                    block_time=datetime.fromtimestamp(block_time, timezone.utc) if block_time else None,
                    data=json.dumps(fields),
                )
            )
            try:
                session.commit()
                new += 1
            except IntegrityError:  # another delivery stored it at the same moment
                session.rollback()
    return new
