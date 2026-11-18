"""Talks to the Loser Buys program on Solana devnet as the oracle.

The oracle is the server-held key that is allowed to end a challenge early and report winners.
Instructions are built by hand from the program's IDL (onchain/idl/loser_buys.json), so the only
dependencies are `solana` and `solders`.

Command line (from api/):
    python chain.py show <challenge>
    python chain.py end-early <challenge>
    python chain.py settle <challenge> <winner> [<winner> ...]

Devnet only. The oracle key is read from the file named by ORACLE_KEYPAIR_PATH.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import config  # noqa: F401  (loads .env before the settings below are read)
from solana.exceptions import SolanaRpcException
from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solana.rpc.types import TxOpts
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import MessageV0
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction

IDL = json.loads((Path(__file__).parent.parent / "onchain" / "idl" / "loser_buys.json").read_text())
PROGRAM_ID = Pubkey.from_string(os.environ.get("PROGRAM_ID") or IDL["address"])
RPC_URL = os.environ.get("SOLANA_RPC_URL") or "https://api.devnet.solana.com"
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
STATUS_NAMES = ["open", "settled", "refunded"]

if "devnet" not in RPC_URL:
    raise RuntimeError(f"Devnet only. Refusing to use {RPC_URL}")


def _discriminator(instruction_name: str) -> bytes:
    """The 8 bytes at the start of the instruction data that tell the program which instruction it is."""
    for ix in IDL["instructions"]:
        if ix["name"] == instruction_name:
            return bytes(ix["discriminator"])
    raise KeyError(instruction_name)


@dataclass
class Challenge:
    address: Pubkey
    creator: Pubkey
    challenge_id: int
    oracle: Pubkey
    mint: Pubkey
    vault: Pubkey
    buy_in: int
    start_time: int
    end_time: int
    max_players: int
    players: list[Pubkey]
    status: str
    score_hash: bytes


def token_account_for(owner: Pubkey, mint: Pubkey) -> Pubkey:
    """A wallet's standard token account for a given token (its "associated token account")."""
    address, _bump = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)], ASSOCIATED_TOKEN_PROGRAM_ID
    )
    return address


def load_keypair(name: str) -> Keypair:
    """Loads a server key. Locally: a file named by <NAME>_KEYPAIR_PATH. On a host with no files: the
    file's contents (a JSON list of numbers) in the secret <NAME>_KEYPAIR."""
    inline = os.environ.get(f"{name}_KEYPAIR")
    path = os.environ.get(f"{name}_KEYPAIR_PATH")
    if inline:
        return Keypair.from_bytes(bytes(json.loads(inline)))
    if not path:
        raise RuntimeError(f"Set {name}_KEYPAIR_PATH (a keypair file) or {name}_KEYPAIR (see .env.example)")
    return Keypair.from_bytes(bytes(json.loads(Path(path).expanduser().read_text())))


def load_oracle() -> Keypair:
    return load_keypair("ORACLE")


def fetch_challenge(client: Client, address: Pubkey) -> Challenge:
    account = _retry(lambda: client.get_account_info(address, commitment=Confirmed)).value
    if account is None or account.owner != PROGRAM_ID:
        raise ValueError(f"{address} is not a Loser Buys challenge")
    data = bytes(account.data)
    pos = 8  # skip the account discriminator

    def take(n: int) -> bytes:
        nonlocal pos
        chunk = data[pos : pos + n]
        pos += n
        return chunk

    creator = Pubkey.from_bytes(take(32))
    (challenge_id,) = struct.unpack("<Q", take(8))
    oracle = Pubkey.from_bytes(take(32))
    mint = Pubkey.from_bytes(take(32))
    vault = Pubkey.from_bytes(take(32))
    buy_in, start_time, end_time = struct.unpack("<Qqq", take(24))
    max_players = take(1)[0]
    (player_count,) = struct.unpack("<I", take(4))
    players = [Pubkey.from_bytes(take(32)) for _ in range(player_count)]
    status = STATUS_NAMES[take(1)[0]]
    score_hash = take(32)
    return Challenge(
        address, creator, challenge_id, oracle, mint, vault, buy_in,
        start_time, end_time, max_players, players, status, score_hash,
    )


def _retry(call, attempts: int = 6):
    """Runs an RPC call, waiting and retrying when the RPC server is rate-limiting us (HTTP 429)."""
    for attempt in range(attempts):
        try:
            return call()
        except SolanaRpcException:
            if attempt == attempts - 1:
                raise
            time.sleep(1.5 * (attempt + 1))


def _send(client: Client, oracle: Keypair, instruction: Instruction) -> str:
    return send_instructions(client, oracle, [instruction])


def send_instructions(client: Client, payer: Keypair, instructions: list[Instruction]) -> str:
    """Signs and sends one transaction paid for by `payer`, waits for it, and returns its signature."""
    blockhash = _retry(lambda: client.get_latest_blockhash(commitment=Confirmed)).value.blockhash
    message = MessageV0.try_compile(payer.pubkey(), instructions, [], blockhash)
    tx = VersionedTransaction(message, [payer])
    # Sent once only: a failed program check raises here (preflight), and must not be retried blindly.
    signature = client.send_transaction(tx, opts=TxOpts(preflight_commitment=Confirmed)).value
    # Wait until the network confirms it (up to about a minute), then make sure it did not fail.
    for _ in range(40):
        status = _retry(lambda: client.get_signature_statuses([signature])).value[0]
        if status is not None and status.err is not None:
            raise RuntimeError(f"Transaction {signature} failed: {status.err}")
        if status is not None and status.confirmation_status is not None and str(
            status.confirmation_status
        ).lower().endswith(("confirmed", "finalized")):
            return str(signature)
        time.sleep(1.5)
    raise TimeoutError(f"Transaction {signature} was not confirmed in time; check it before retrying")


def end_early(client: Client, oracle: Keypair, challenge: Pubkey) -> str:
    """Ends the challenge now. Returns the transaction signature."""
    instruction = Instruction(
        PROGRAM_ID,
        _discriminator("end_early"),
        [
            AccountMeta(oracle.pubkey(), is_signer=True, is_writable=False),
            AccountMeta(challenge, is_signer=False, is_writable=True),
        ],
    )
    return _send(client, oracle, instruction)


def _settle_accounts(state: "Challenge", oracle: Keypair, challenge: Pubkey, winners: list[Pubkey]) -> list[AccountMeta]:
    accounts = [
        AccountMeta(oracle.pubkey(), is_signer=True, is_writable=False),
        AccountMeta(challenge, is_signer=False, is_writable=True),
        AccountMeta(state.vault, is_signer=False, is_writable=True),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    # One token account per winner, in the same order as the winner list.
    return accounts + [
        AccountMeta(token_account_for(w, state.mint), is_signer=False, is_writable=True) for w in winners
    ]


def _pubkeys(keys: list[Pubkey]) -> bytes:
    return struct.pack("<I", len(keys)) + b"".join(bytes(k) for k in keys)


def settle(client: Client, oracle: Keypair, challenge: Pubkey, winners: list[Pubkey], score_hash: bytes) -> str:
    """Reports the winners and pays out the pool in equal shares. Returns the transaction signature."""
    if len(score_hash) != 32:
        raise ValueError("score_hash must be 32 bytes (a SHA-256 digest)")
    state = fetch_challenge(client, challenge)
    data = _discriminator("settle") + _pubkeys(winners) + score_hash
    return _send(client, oracle, Instruction(PROGRAM_ID, data, _settle_accounts(state, oracle, challenge, winners)))


def settle_split(
    client: Client, oracle: Keypair, challenge: Pubkey, winners: list[Pubkey], shares_bps: list[int], score_hash: bytes
) -> str:
    """Pays the pool in fixed shares (basis points, adding up to 10,000), for example a podium.
    Returns the transaction signature."""
    if len(score_hash) != 32:
        raise ValueError("score_hash must be 32 bytes (a SHA-256 digest)")
    if len(shares_bps) != len(winners) or sum(shares_bps) != 10_000:
        raise ValueError("need one share per winner, adding up to 10,000 basis points")
    state = fetch_challenge(client, challenge)
    data = (
        _discriminator("settle_split")
        + _pubkeys(winners)
        + struct.pack("<I", len(shares_bps))
        + b"".join(struct.pack("<H", s) for s in shares_bps)
        + score_hash
    )
    return _send(client, oracle, Instruction(PROGRAM_ID, data, _settle_accounts(state, oracle, challenge, winners)))


def refund(client: Client, payer: Keypair, challenge: Pubkey) -> str:
    """Returns every buy-in. The program allows it when fewer than 2 players joined by the start time,
    or 72 hours after the end with no result. Anyone may call it; `payer` only pays the fee."""
    state = fetch_challenge(client, challenge)
    accounts = [
        AccountMeta(payer.pubkey(), is_signer=True, is_writable=False),
        AccountMeta(challenge, is_signer=False, is_writable=True),
        AccountMeta(state.vault, is_signer=False, is_writable=True),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    # One token account per player, in the same order as the player list.
    accounts += [
        AccountMeta(token_account_for(p, state.mint), is_signer=False, is_writable=True) for p in state.players
    ]
    return _send(client, payer, Instruction(PROGRAM_ID, _discriminator("refund"), accounts))


def recent_transactions(client: Client, address: Pubkey, skip: set[str], limit: int = 25) -> list[dict]:
    """Recent successful transactions that touched `address`, in the shape the QuickNode Stream delivers.

    Used only to catch up on events the Stream could not deliver (it cannot replay missed blocks).
    """
    found = []
    signatures = _retry(lambda: client.get_signatures_for_address(address, limit=limit, commitment=Confirmed)).value
    for entry in reversed(signatures):  # oldest first
        if entry.err is not None or str(entry.signature) in skip:
            continue
        tx = _retry(
            lambda: client.get_transaction(entry.signature, commitment=Confirmed, max_supported_transaction_version=0)
        ).value
        if tx is None or tx.transaction.meta is None:
            continue
        found.append(
            {
                "signature": str(entry.signature),
                "slot": tx.slot,
                "blockTime": tx.block_time,
                "logs": list(tx.transaction.meta.log_messages or []),
            }
        )
    return found


def _main(argv: list[str]) -> None:
    if len(argv) < 3:
        print(__doc__)
        sys.exit(2)
    command, challenge = argv[1], Pubkey.from_string(argv[2])
    client = Client(RPC_URL)
    explorer = "https://explorer.solana.com/tx/{}?cluster=devnet"
    if command == "show":
        print(fetch_challenge(client, challenge))
    elif command == "end-early":
        print("end_early:", explorer.format(end_early(client, load_oracle(), challenge)))
    elif command == "settle":
        winners = [Pubkey.from_string(w) for w in argv[3:]]
        score_hash = hashlib.sha256(b"command-line-settle").digest()
        print("settle:", explorer.format(settle(client, load_oracle(), challenge, winners, score_hash)))
        print("status now:", fetch_challenge(client, challenge).status)
    else:
        print(__doc__)
        sys.exit(2)


if __name__ == "__main__":
    _main(sys.argv)
