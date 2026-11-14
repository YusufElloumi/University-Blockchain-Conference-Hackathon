"""Sends test money from the server's treasury wallet on Solana devnet.

Two jobs:
- gas drip: a little devnet SOL so a new user's wallet can pay transaction fees without them knowing
- test funds: devnet USDC that stands in for a card payment in the demo

Devnet only. The treasury key is read from the file named by TREASURY_KEYPAIR_PATH.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

from solana.rpc.api import Client
from solana.rpc.commitment import Confirmed
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID
from solders.system_program import TransferParams, transfer

import chain
import config

USDC_MINT = Pubkey.from_string(config.USDC_MINT)
_treasury: Keypair | None = None


def load_treasury() -> Keypair:
    global _treasury
    if _treasury is None:
        path = os.environ.get("TREASURY_KEYPAIR_PATH")
        if not path:
            raise RuntimeError("Set TREASURY_KEYPAIR_PATH to the treasury keypair file (see .env.example)")
        _treasury = Keypair.from_bytes(bytes(json.loads(Path(path).expanduser().read_text())))
    return _treasury


def _client() -> Client:
    return Client(chain.RPC_URL)


def sol_balance(wallet: Pubkey) -> int:
    """Balance in lamports (1 SOL = 1,000,000,000 lamports)."""
    client = _client()
    return chain._retry(lambda: client.get_balance(wallet, commitment=Confirmed)).value


def usdc_balance(wallet: Pubkey) -> int:
    """USDC balance in the token's smallest unit (1 USDC = 1,000,000). 0 if the wallet has no USDC account."""
    client = _client()
    token_account = chain.token_account_for(wallet, USDC_MINT)
    account = chain._retry(lambda: client.get_account_info(token_account, commitment=Confirmed)).value
    if account is None:
        return 0
    # A token account stores: mint (32 bytes), owner (32 bytes), amount (8 bytes), ...
    return struct.unpack("<Q", bytes(account.data)[64:72])[0]


def send_gas(wallet: Pubkey, lamports: int = config.GAS_DRIP_LAMPORTS) -> str:
    """Sends fee money (SOL) to a user's wallet. Returns the transaction signature."""
    treasury = load_treasury()
    instruction = transfer(TransferParams(from_pubkey=treasury.pubkey(), to_pubkey=wallet, lamports=lamports))
    return chain.send_instructions(_client(), treasury, [instruction])


def send_usdc(wallet: Pubkey, units: int = config.TEST_FUNDS_UNITS) -> str:
    """Sends test USDC to a user's wallet, creating their USDC account first if needed (treasury pays)."""
    treasury = load_treasury()
    source = chain.token_account_for(treasury.pubkey(), USDC_MINT)
    destination = chain.token_account_for(wallet, USDC_MINT)
    # "Create the user's USDC account unless it already exists" (instruction 1 of the associated token program).
    create_account = Instruction(
        chain.ASSOCIATED_TOKEN_PROGRAM_ID,
        bytes([1]),
        [
            AccountMeta(treasury.pubkey(), is_signer=True, is_writable=True),
            AccountMeta(destination, is_signer=False, is_writable=True),
            AccountMeta(wallet, is_signer=False, is_writable=False),
            AccountMeta(USDC_MINT, is_signer=False, is_writable=False),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            AccountMeta(chain.TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
    )
    # "Transfer, and check the mint and decimals" (instruction 12 of the token program).
    send = Instruction(
        chain.TOKEN_PROGRAM_ID,
        bytes([12]) + struct.pack("<QB", units, config.USDC_DECIMALS),
        [
            AccountMeta(source, is_signer=False, is_writable=True),
            AccountMeta(USDC_MINT, is_signer=False, is_writable=False),
            AccountMeta(destination, is_signer=False, is_writable=True),
            AccountMeta(treasury.pubkey(), is_signer=True, is_writable=False),
        ],
    )
    return chain.send_instructions(_client(), treasury, [create_account, send])
