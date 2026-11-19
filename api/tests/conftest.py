import os
import sys
from pathlib import Path

# Tests never touch the real database, Privy, or devnet.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["PRIVY_APP_ID"] = "test-app-id"
os.environ["PRIVY_APP_SECRET"] = "test-secret"
# The older suites exercise the self-reported rules; Proof of Sweat tests switch this themselves.
os.environ["NEW_CHALLENGE_RULES"] = "daily_mover"
sys.path.insert(0, str(Path(__file__).parent.parent))
