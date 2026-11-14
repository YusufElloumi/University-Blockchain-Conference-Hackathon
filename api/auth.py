"""Checks who is calling the API, using the login token that Privy gives the web app.

The token is a JWT (a signed piece of JSON). We check Privy's signature (ES256), that it has not
expired, that Privy issued it (issuer "privy.io"), and that it was issued for our app (audience =
our Privy app ID). The user's ID is the "sub" field, for example "did:privy:abc123".
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import jwt
from fastapi import Header, HTTPException

import config

_JWKS_URL = "https://auth.privy.io/api/v1/apps/{app_id}/jwks.json"
_USER_URL = "https://auth.privy.io/api/v1/users/{user_id}"
_jwks_client: jwt.PyJWKClient | None = None


class AuthError(Exception):
    pass


@dataclass
class PrivyUser:
    privy_id: str
    email: str | None
    wallet: str | None  # the embedded Solana wallet Privy created for this user


def _signing_keys() -> list:
    """Privy's public keys for our app, downloaded once and cached."""
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = jwt.PyJWKClient(
            _JWKS_URL.format(app_id=config.PRIVY_APP_ID),
            cache_jwk_set=True,
            lifespan=3600,
            headers={"User-Agent": "python-jwks"},
        )
    return [k.key for k in _jwks_client.get_signing_keys()]


def verify_access_token(token: str) -> str:
    """Returns the user's Privy ID if the token is valid; raises AuthError otherwise."""
    if not config.PRIVY_APP_ID:
        raise AuthError("PRIVY_APP_ID is not set on the server")
    try:
        keys = _signing_keys()
    except jwt.PyJWTError as e:
        raise AuthError(f"Could not load Privy's verification keys: {e}") from e
    last_error: Exception = AuthError("No verification keys")
    for key in keys:
        try:
            claims = jwt.decode(
                token,
                key,
                algorithms=["ES256"],
                issuer="privy.io",
                audience=config.PRIVY_APP_ID,
                options={"require": ["exp", "iss", "aud", "sub"]},
            )
            return claims["sub"]
        except jwt.InvalidSignatureError as e:
            last_error = e  # signed by a different key; try the next one
        except jwt.PyJWTError as e:
            raise AuthError(str(e)) from e
    raise AuthError(str(last_error) or "Invalid signature")


def fetch_privy_user(privy_id: str) -> PrivyUser:
    """Asks Privy for the user's email and embedded Solana wallet address.

    The wallet address comes from Privy, never from the browser, so nobody can ask for
    test funds to be sent to a wallet that is not theirs.
    """
    response = httpx.get(
        _USER_URL.format(user_id=privy_id),
        auth=(config.PRIVY_APP_ID, config.PRIVY_APP_SECRET),
        headers={"privy-app-id": config.PRIVY_APP_ID},
        timeout=15,
    )
    response.raise_for_status()
    email = wallet = None
    for account in response.json().get("linked_accounts", []):
        kind = account.get("type")
        if kind == "email":
            email = account.get("address")
        elif (
            kind == "wallet"
            and (account.get("chain_type") or account.get("chainType")) == "solana"
            and (account.get("wallet_client_type") or account.get("walletClientType")) == "privy"
        ):
            wallet = wallet or account.get("address")
    return PrivyUser(privy_id, email, wallet)


def current_privy_id(authorization: str | None = Header(default=None)) -> str:
    """FastAPI dependency: reads "Authorization: Bearer <token>" and returns the Privy user ID."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Missing login token")
    try:
        return verify_access_token(authorization[7:].strip())
    except AuthError as e:
        raise HTTPException(401, f"Invalid login token: {e}") from e
