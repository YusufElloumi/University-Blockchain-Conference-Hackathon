"""Proof of Effort ("Proof of Sweat" on screen): a signed record of a challenge's final result.

Version 2 (challenges with locked rules): the verifier signs a fixed binary message, and the program
itself checks that signature at payout. The settle transaction carries Solana's Ed25519 signature
check right before `settle` / `settle_split`; the program reads the signed message from it and pays
only the winners and shares it names, for this challenge and its committed rules hash. Layout
(see `message_v2` and docs/ARCHITECTURE.md):
    "rival.proof-of-effort.v2" | program | challenge | rules_hash | score_hash | count | winners | shares

Version 1 (older challenges): a signed JSON message, checked only offchain. Still verifiable here.


When a challenge settles, the verifier key signs a short message saying: "under rules X, the score
sheet with this SHA-256 produced this payout, for this challenge, on this program, on devnet".

What a proof shows:
  - our verifier approved this exact result (Ed25519 signature, the same kind Solana wallets use);
  - the score sheet was not changed afterwards (its SHA-256 is also stored onchain by `settle`);
  - the proof cannot be reused for another challenge, program or network (all three are in the
    signed message, together with a fixed domain label).

What it does NOT show: that a workout really happened. It shows that our verifier accepted it.

No fitness data is in a proof: only addresses, payout shares, hashes, a rules version and times.
The proof stays offchain; the chain holds only the winner addresses and the salted sheet hash.

Command line (from api/), for anyone holding a proof saved from GET /challenges/<address>/score-sheet:
    python attest.py verify <proof.json>
"""

from __future__ import annotations

import base64
import hashlib
import json
import struct
import secrets
import sys
import time

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.signature import Signature

import chain
import config
import formats

DOMAIN = "rival.proof-of-effort"
SCHEMA = 1
DOMAIN_V2 = b"rival.proof-of-effort.v2"
SCHEMA_V2 = 2
SWEAT_SCHEMA = 2  # Proof of Sweat sheets: adds the receipt commitments summary
CLUSTER = "devnet"


def canonical(value: object) -> str:
    """Compact JSON with sorted keys and only ASCII characters: the same value always gives the same text."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sheet_sha256(sheet: dict) -> bytes:
    """SHA-256 of the score sheet in canonical form. This is the hash `settle` stores onchain."""
    return hashlib.sha256(canonical(sheet).encode()).digest()


def load_verifier() -> Keypair | None:
    """The verifier key, or None when it is not configured (settlement still works, just without a proof)."""
    try:
        return chain.load_keypair("VERIFIER")
    except RuntimeError:
        return None


def build(challenge: str, sheet: dict, payout: formats.Payout, verifier: Pubkey,
          now: int | None = None, nonce: str | None = None) -> dict:
    """The message to sign. Every field is public information."""
    payload = _payload(challenge, sheet, payout, verifier, now, nonce)
    section = sheet.get("proof_of_sweat")
    if section:
        # Schema 2: the proof also names how many workout receipts the sheet commits to, and one hash over them.
        commitments = [c for p in section.get("participants", []) for c in p.get("receipts", [])]
        payload["schema"] = SWEAT_SCHEMA
        payload["proof_of_sweat"] = {"receipts": len(commitments), "receipts_sha256": receipts_sha256(commitments)}
    return payload


def receipts_sha256(commitments: list[str]) -> str:
    return sheet_sha256(sorted(commitments)).hex()


def _payload(challenge: str, sheet: dict, payout: formats.Payout, verifier: Pubkey,
             now: int | None = None, nonce: str | None = None) -> dict:
    return {
        "schema": SCHEMA,
        "domain": DOMAIN,
        "cluster": CLUSTER,
        "program": str(chain.PROGRAM_ID),
        "challenge": challenge,
        "rules": {
            "name": sheet.get("rules"),
            "version": sheet.get("rules_version"),
            "sha256": sheet.get("rules_sha256"),
        },
        "score_sheet_sha256": sheet_sha256(sheet).hex(),
        "payout": [{"wallet": wallet, "bps": bps} for wallet, bps in payout.shares],
        "issued_at": int(time.time()) if now is None else now,
        "nonce": nonce or secrets.token_hex(16),  # makes every proof unique, even for the same result
        "verifier": str(verifier),
    }


def sign(payload: dict, keypair: Keypair) -> dict:
    """A proof: the exact signed text, the signature, and who signed it."""
    message = canonical(payload)
    return {
        "message": message,
        "signature": bytes(keypair.sign_message(message.encode())).hex(),
        "verifier": str(keypair.pubkey()),
    }


def issue(challenge: str, sheet: dict, payout: formats.Payout, keypair: Keypair) -> dict:
    return sign(build(challenge, sheet, payout, keypair.pubkey()), keypair)


def check(proof: dict, *, challenge: str, sheet: dict | None = None, trusted: str | None = None,
          onchain_hash: bytes | None = None) -> list[str]:
    """Everything wrong with a proof, in plain words. An empty list means it checks out.

    `trusted` is the verifier public key we expect (default: the published one in config).
    `sheet`, when given, must hash to the signed value and give the signed payout.
    `onchain_hash`, when given, is the challenge account's `score_hash` and must match too.
    """
    import settlement  # here, not at the top: settlement imports this module

    trusted = trusted or config.VERIFIER_PUBLIC_KEY
    problems: list[str] = []
    try:
        message = proof["message"]
        payload = json.loads(message)
        signature = Signature.from_bytes(bytes.fromhex(proof["signature"]))
        signer = Pubkey.from_string(payload["verifier"])
    except (KeyError, TypeError, ValueError) as e:
        return [f"not a readable proof ({e.__class__.__name__})"]

    if canonical(payload) != message:
        problems.append("the message is not in canonical form")
    if str(signer) != trusted:
        problems.append(f"signed by {signer}, not by the published verifier {trusted}")
    if not signature.verify(signer, message.encode()):
        problems.append("the signature does not match the message")
    wanted = SWEAT_SCHEMA if "proof_of_sweat" in payload else SCHEMA
    if payload.get("schema") != wanted:
        problems.append(f"schema is {payload.get('schema')!r}, expected {wanted!r}")
    expected = {"domain": DOMAIN, "cluster": CLUSTER, "program": str(chain.PROGRAM_ID), "challenge": challenge}
    for field, value in expected.items():
        if payload.get(field) != value:
            problems.append(f"{field} is {payload.get(field)!r}, expected {value!r}")
    if sheet is not None:
        if sheet_sha256(sheet).hex() != payload.get("score_sheet_sha256"):
            problems.append("the score sheet does not match the signed hash")
        if sheet.get("challenge") != challenge:
            problems.append("the score sheet is for another challenge")
        section = sheet.get("proof_of_sweat")
        if section or payload.get("proof_of_sweat"):
            commitments = [c for p in (section or {}).get("participants", []) for c in p.get("receipts", [])]
            signed = payload.get("proof_of_sweat") or {}
            if signed.get("receipts") != len(commitments) or signed.get("receipts_sha256") != receipts_sha256(commitments):
                problems.append("the workout receipt commitments do not match the signed summary")
        paid = [{"wallet": w, "bps": bps} for w, bps in settlement.payout_of(sheet).shares]
        if paid != payload.get("payout"):
            problems.append("the signed payout is not what the score sheet gives")
    if onchain_hash is not None and onchain_hash.hex() != payload.get("score_sheet_sha256"):
        problems.append("the signed hash is not the one stored onchain")
    return problems


# ---------- version 2: the message the program checks ----------


def message_v2(program: Pubkey, challenge: Pubkey, rules_hash: bytes, score_hash: bytes,
               winners: list[Pubkey], shares_bps: list[int]) -> bytes:
    """The exact bytes the verifier signs and the program reads (onchain/programs/loser_buys/src/proof.rs)."""
    if len(rules_hash) != 32 or len(score_hash) != 32:
        raise ValueError("hashes must be 32 bytes")
    if not 1 <= len(winners) <= 8 or len(shares_bps) != len(winners):
        raise ValueError("need 1 to 8 winners and one share each")
    return (
        DOMAIN_V2 + bytes(program) + bytes(challenge) + rules_hash + score_hash + bytes([len(winners)])
        + b"".join(bytes(w) for w in winners) + b"".join(struct.pack("<H", s) for s in shares_bps)
    )


def parse_v2(message: bytes) -> dict:
    """The readable fields of a v2 message. Raises ValueError if it is malformed."""
    fixed = len(DOMAIN_V2) + 32 * 4 + 1
    if len(message) <= fixed or not message.startswith(DOMAIN_V2):
        raise ValueError("not a v2 message")
    at = len(DOMAIN_V2)
    program, challenge, rules_hash, score_hash = (message[at + 32 * i: at + 32 * (i + 1)] for i in range(4))
    count = message[fixed - 1]
    if not 1 <= count <= 8 or len(message) != fixed + 34 * count:
        raise ValueError("wrong winner count")
    winners = [str(Pubkey.from_bytes(message[fixed + 32 * i: fixed + 32 * (i + 1)])) for i in range(count)]
    shares_at = fixed + 32 * count
    shares = [struct.unpack_from("<H", message, shares_at + 2 * i)[0] for i in range(count)]
    return {"program": str(Pubkey.from_bytes(program)), "challenge": str(Pubkey.from_bytes(challenge)),
            "rules_hash": rules_hash.hex(), "score_sheet_sha256": score_hash.hex(),
            "payout": [{"wallet": w, "bps": b} for w, b in zip(winners, shares)]}


def issue_v2(challenge: str, rules_hash: bytes, sheet: dict, shares: list[tuple[str, int]], keypair: Keypair) -> dict:
    """A v2 proof: readable fields, the signed bytes (base64) and the signature. The settlement
    transaction is added once it is sent (`settle_tx`)."""
    message = message_v2(chain.PROGRAM_ID, Pubkey.from_string(challenge), rules_hash, sheet_sha256(sheet),
                         [Pubkey.from_string(w) for w, _ in shares], [b for _, b in shares])
    return {
        "schema": SCHEMA_V2,
        "domain": DOMAIN_V2.decode(),
        "cluster": CLUSTER,
        **parse_v2(message),
        "message": base64.b64encode(message).decode(),
        "signature": bytes(keypair.sign_message(message)).hex(),
        "verifier": str(keypair.pubkey()),
        "issued_at": int(time.time()),
        "settle_tx": None,
        "checked_onchain": True,
        **_sweat_summary(sheet),
    }


def _sweat_summary(sheet: dict) -> dict:
    """Proof of Sweat sheets: how many workout receipts the sheet commits to, and one hash over them.
    Not part of the signed bytes; it is covered by the signed score-sheet hash, and check_v2 recomputes it."""
    section = sheet.get("proof_of_sweat")
    if not section:
        return {}
    commitments = [c for p in section.get("participants", []) for c in p.get("receipts", [])]
    return {"proof_of_sweat": {"receipts": len(commitments), "receipts_sha256": receipts_sha256(commitments)}}


def check_v2(proof: dict, *, challenge: str, sheet: dict | None = None, trusted: str | None = None,
             onchain_hash: bytes | None = None, onchain_rules_hash: bytes | None = None,
             ruleset_text: str | None = None) -> list[str]:
    """Everything wrong with a v2 proof, in plain words. An empty list means it checks out."""
    import settlement  # here, not at the top: settlement imports this module
    trusted = trusted or config.VERIFIER_PUBLIC_KEY
    problems: list[str] = []
    try:
        message = base64.b64decode(proof["message"])
        fields = parse_v2(message)
        signature = Signature.from_bytes(bytes.fromhex(proof["signature"]))
        signer = Pubkey.from_string(proof["verifier"])
    except (KeyError, TypeError, ValueError) as e:
        return [f"not a readable proof ({e.__class__.__name__})"]
    for field, value in fields.items():
        if proof.get(field) != value:
            problems.append(f"the readable {field} does not match the signed message")
    if str(signer) != trusted:
        problems.append(f"signed by {signer}, not by the published verifier {trusted}")
    if not signature.verify(signer, message):
        problems.append("the signature does not match the message")
    if fields["program"] != str(chain.PROGRAM_ID):
        problems.append("it is for another program")
    if fields["challenge"] != challenge:
        problems.append("it is for another challenge")
    if sheet is not None:
        if sheet_sha256(sheet).hex() != fields["score_sheet_sha256"]:
            problems.append("the score sheet does not match the signed hash")
        if sheet.get("challenge") != challenge:
            problems.append("the score sheet is for another challenge")
        if _sweat_summary(sheet).get("proof_of_sweat") != proof.get("proof_of_sweat"):
            problems.append("the workout receipt commitments do not match the summary")
        paid = [{"wallet": w, "bps": bps} for w, bps in settlement.payout_of(sheet).shares]
        if paid != fields["payout"]:
            problems.append("the signed payout is not what the score sheet gives")
    if ruleset_text is not None and hashlib.sha256(ruleset_text.encode()).hexdigest() != fields["rules_hash"]:
        problems.append("the published rules do not hash to the signed rules hash")
    if onchain_hash is not None and onchain_hash.hex() != fields["score_sheet_sha256"]:
        problems.append("the signed score hash is not the one stored onchain")
    if onchain_rules_hash is not None and onchain_rules_hash.hex() != fields["rules_hash"]:
        problems.append("the signed rules hash is not the one locked onchain")
    return problems


def check_any(proof: dict, **kwargs) -> list[str]:
    """Checks a proof of either version. v1 ignores the rules arguments (it has no rules hash)."""
    if proof.get("schema") == SCHEMA_V2:
        return check_v2(proof, **kwargs)
    kwargs.pop("onchain_rules_hash", None)
    kwargs.pop("ruleset_text", None)
    return check(proof, **kwargs)


def _main(args: list[str]) -> int:
    if len(args) != 2 or args[0] != "verify":
        print(__doc__)
        return 2
    with open(args[1], encoding="utf-8-sig") as f:  # -sig: also reads files saved by Windows tools
        saved = json.load(f)
    proof = saved.get("proof") or saved
    from solana.rpc.api import Client
    client = Client(chain.RPC_URL)
    if proof.get("schema") == SCHEMA_V2:
        address = proof["challenge"]
        state = chain.fetch_challenge(client, Pubkey.from_string(address))
        locked = chain.fetch_rules(client, Pubkey.from_string(address))
        problems = check_v2(proof, challenge=address, sheet=saved.get("sheet"), onchain_hash=state.score_hash,
                            onchain_rules_hash=locked.rules_hash if locked else None,
                            ruleset_text=saved.get("ruleset"))
        if locked is None:
            problems.append("the challenge has no rules account onchain")
        ok = ("OK: signed by the published verifier, the signature was checked by the program at payout, "
              "and the score and rules hashes match the chain.")
    else:
        address = json.loads(proof["message"])["challenge"]
        state = chain.fetch_challenge(client, Pubkey.from_string(address))
        problems = check(proof, challenge=address, sheet=saved.get("sheet"), onchain_hash=state.score_hash)
        ok = "OK (v1): signed by the published verifier, and the hash matches the chain. Signed, not checked onchain."
    if state.status != "settled":
        problems.append(f"the challenge is {state.status}, not settled")
    for line in problems or [ok]:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
