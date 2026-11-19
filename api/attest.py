"""Proof of Effort: a signed record of a challenge's final result that anyone can check.

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

import hashlib
import json
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


def _main(args: list[str]) -> int:
    if len(args) != 2 or args[0] != "verify":
        print(__doc__)
        return 2
    with open(args[1], encoding="utf-8-sig") as f:  # -sig: also reads files saved by Windows tools
        saved = json.load(f)
    proof = saved.get("proof") or saved
    payload = json.loads(proof["message"])
    address = payload["challenge"]
    from solana.rpc.api import Client

    state = chain.fetch_challenge(Client(chain.RPC_URL), Pubkey.from_string(address))
    problems = check(proof, challenge=address, sheet=saved.get("sheet"), onchain_hash=state.score_hash)
    if state.status != "settled":
        problems.append(f"the challenge is {state.status}, not settled")
    for line in problems or ["OK: signed by the published verifier, and the hash matches the chain."]:
        print(line)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
