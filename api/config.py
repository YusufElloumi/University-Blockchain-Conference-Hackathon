"""Loads settings from the repo's .env file. Import this before any module that reads os.environ."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

API_DIR = Path(__file__).parent
load_dotenv(API_DIR.parent / ".env")

PRIVY_APP_ID = os.environ.get("PRIVY_APP_ID", "")
PRIVY_APP_SECRET = os.environ.get("PRIVY_APP_SECRET", "")
WEB_ORIGINS = [o.strip() for o in (os.environ.get("WEB_ORIGIN") or "http://localhost:5173").split(",") if o.strip()]
DATABASE_URL = os.environ.get("DATABASE_URL") or f"sqlite:///{(API_DIR / 'loser_buys.db').as_posix()}"
if DATABASE_URL.startswith(("postgres://", "postgresql://")):
    # Hosts such as Neon hand out a plain postgres address; tell SQLAlchemy which driver to use.
    DATABASE_URL = "postgresql+psycopg://" + DATABASE_URL.split("://", 1)[1]
USDC_MINT = os.environ.get("USDC_MINT") or "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"
USDC_DECIMALS = 6
QUICKNODE_STREAM_SECURITY_TOKEN = os.environ.get("QUICKNODE_STREAM_SECURITY_TOKEN", "")
FITNESS_PROVIDER = os.environ.get("FITNESS_PROVIDER") or "mock"  # mock, manual, or strava
# The oracle's public address (not its key). New challenges must name it, or we could never settle them.
ORACLE_PUBLIC_KEY = os.environ.get("ORACLE_PUBLIC_KEY") or "6EEkAR114PYKhJJCWBiJLb342VAMNF69H6dmAB8MtFdD"

# Settlement. Grace period: how long after the end we wait for late activities (0 for demos; 12 hours suits Strava).
SETTLE_GRACE_SECONDS = int(os.environ.get("SETTLE_GRACE_SECONDS") or 0)
ADMIN_EMAILS = {e.strip().lower() for e in (os.environ.get("ADMIN_EMAILS") or "").split(",") if e.strip()}
TICK_SECRET = os.environ.get("TICK_SECRET", "")  # shared secret for the scheduler that calls /internal/tick

# "Gas drip": fee money (devnet SOL) the server quietly sends to a user's wallet so they never see fees.
GAS_DRIP_LAMPORTS = int(float(os.environ.get("GAS_DRIP_SOL") or 0.02) * 1_000_000_000)
GAS_LOW_LAMPORTS = 5_000_000  # top up when a wallet holds less than 0.005 SOL
GAS_DRIP_MAX_PER_USER = 3

# "Add test funds": devnet USDC the server sends once per user (stands in for a card payment).
TEST_FUNDS_UNITS = int(float(os.environ.get("TEST_FUNDS_USDC") or 5) * 10**USDC_DECIMALS)
