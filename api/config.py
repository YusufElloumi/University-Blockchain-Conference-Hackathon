"""Loads settings from the repo's .env file. Import this before any module that reads os.environ."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).parent
load_dotenv(API_DIR.parent / ".env")

PRIVY_APP_ID = os.environ.get("PRIVY_APP_ID", "")
PRIVY_APP_SECRET = os.environ.get("PRIVY_APP_SECRET", "")
def clean_origin(value: str) -> str:
    """A web address cut down to what a browser sends as its origin: scheme and host, no path or slash."""
    value = value.strip().strip("\"'").strip()
    scheme, separator, rest = value.partition("://")
    return f"{scheme}://{rest.split('/', 1)[0]}" if separator else value.rstrip("/")


WEB_ORIGINS = [
    clean_origin(o) for o in (os.environ.get("WEB_ORIGIN") or "http://localhost:5173").split(",") if o.strip()
]


def clean_database_url(value: str) -> str:
    """Tidies a database address pasted into a host's settings page.

    Forgives the usual copy-paste slips: spaces or line breaks around it, quote marks, a leading
    `DATABASE_URL=`, or the whole `psql '...'` command. Fails with a plain message (never showing
    the address, which holds a password) if what is left is not a database address.
    """
    value = value.strip()
    if value.startswith("psql "):
        value = value[5:].strip()
    if value.startswith("DATABASE_URL="):
        value = value[len("DATABASE_URL="):].strip()
    value = value.strip("\"'").strip()
    if value.startswith(("postgres://", "postgresql://")):
        # Hosts such as Neon hand out a plain postgres address; tell SQLAlchemy which driver to use.
        value = "postgresql+psycopg://" + value.split("://", 1)[1]
    if not value.startswith(("postgresql+psycopg://", "sqlite://")) or any(c.isspace() for c in value):
        raise RuntimeError(
            "DATABASE_URL is not a database address. It must be one line starting with postgresql:// "
            f"(got {len(value)} characters starting with {value[:8]!r})."
        )
    return value


DATABASE_URL = clean_database_url(os.environ.get("DATABASE_URL") or f"sqlite:///{(API_DIR / 'loser_buys.db').as_posix()}")
USDC_MINT = os.environ.get("USDC_MINT") or "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
USDC_DECIMALS = 6
QUICKNODE_STREAM_SECURITY_TOKEN = os.environ.get("QUICKNODE_STREAM_SECURITY_TOKEN", "")
FITNESS_PROVIDER = os.environ.get("FITNESS_PROVIDER") or "mock"  # mock, manual, or strava
# The oracle's public address (not its key). New challenges must name it, or we could never settle them.
ORACLE_PUBLIC_KEY = os.environ.get("ORACLE_PUBLIC_KEY") or "6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD"
# The verifier's public address: Proof of Effort records must be signed by it. Also published in the
# README and in web/src/proof.ts, so a proof can be checked without asking our server who to trust.
VERIFIER_PUBLIC_KEY = os.environ.get("VERIFIER_PUBLIC_KEY") or "5hapcEHu65LyQhqD3Tqtrwm1ftzBnAm93c6jnc8gcway"

# Which fitness rules a NEW challenge gets (api/sweat.py). Production leaves this unset: Proof of Sweat,
# scored only from workouts imported from a player's own connected Oura account. "daily_mover" is the
# old self-reported rule set, kept for the automated tests and for challenges created before Proof of Sweat.
# "proof_of_sweat_v1" is the first Proof of Sweat (1 point per 10 minutes); challenges locked to it keep it.
NEW_CHALLENGE_RULES = os.environ.get("NEW_CHALLENGE_RULES") or "proof_of_sweat_v3"
# Proof of Sweat settlement: wait this long after the end so rings can sync (not a guarantee that they will),
# and stop waiting for a missing final sync this long after the end.
SYNC_GRACE_SECONDS = int(os.environ.get("SYNC_GRACE_SECONDS") or 30 * 60)
SYNC_GIVE_UP_SECONDS = int(os.environ.get("SYNC_GIVE_UP_SECONDS") or 6 * 60 * 60)
# Imported workouts are deleted this many days after the last challenge that needed them ended.
EVIDENCE_RETENTION_DAYS = int(os.environ.get("EVIDENCE_RETENTION_DAYS") or 7)

# Settlement. Grace period: how long after the end we wait for late activities (0 for demos; 12 hours suits Strava).
SETTLE_GRACE_SECONDS = int(os.environ.get("SETTLE_GRACE_SECONDS") or 0)
ADMIN_EMAILS = {e.strip().lower() for e in (os.environ.get("ADMIN_EMAILS") or "").split(",") if e.strip()}
TICK_SECRET = os.environ.get("TICK_SECRET", "")  # shared secret for the scheduler that calls /internal/tick

# "Gas drip": fee money (devnet SOL) the server quietly sends to a user's wallet so they never see fees.
GAS_DRIP_LAMPORTS = int(float(os.environ.get("GAS_DRIP_SOL") or 0.02) * 1_000_000_000)
GAS_LOW_LAMPORTS = 5_000_000  # top up when a wallet holds less than 0.005 SOL
GAS_DRIP_MAX_PER_USER = 3

# Oura Ring connection (api/fitness/oura.py). All four must be set, or "Connect Oura" says it is unavailable.
# The redirect URI must match the one registered in the Oura developer portal exactly.
OURA_CLIENT_ID = os.environ.get("OURA_CLIENT_ID", "").strip()
OURA_CLIENT_SECRET = os.environ.get("OURA_CLIENT_SECRET", "").strip()
OURA_REDIRECT_URI = os.environ.get("OURA_REDIRECT_URI", "").strip()
# Encrypts outside services' tokens in the database (api/secretbox.py). One or more Fernet keys,
# comma-separated, newest first: to rotate, put a new key in front and keep the old one until re-saved.
TOKEN_ENCRYPTION_KEY = os.environ.get("TOKEN_ENCRYPTION_KEY", "").strip()

# "Add test funds": devnet USDC the server sends once per user (stands in for a card payment).
TEST_FUNDS_UNITS = int(float(os.environ.get("TEST_FUNDS_USDC") or 5) * 10**USDC_DECIMALS)
