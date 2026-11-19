"""Encrypts secrets we must keep in the database, such as an outside service's access tokens.

Uses Fernet (AES-128-CBC with an HMAC-SHA256 check) from the `cryptography` package. The key lives
only in the server's environment (TOKEN_ENCRYPTION_KEY), never in the database or the code, so a
copy of the database alone does not reveal the tokens.

Make a key (run once, store the output as a secret on the host and in your local .env):
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

import config


class NotConfigured(Exception):
    """TOKEN_ENCRYPTION_KEY is missing or not a valid key."""


def _box() -> MultiFernet:
    keys = [k.strip() for k in config.TOKEN_ENCRYPTION_KEY.split(",") if k.strip()]
    if not keys:
        raise NotConfigured("TOKEN_ENCRYPTION_KEY is not set")
    try:
        return MultiFernet([Fernet(k) for k in keys])
    except (ValueError, TypeError) as e:
        raise NotConfigured("TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from None


def is_configured() -> bool:
    try:
        _box()
        return True
    except NotConfigured:
        return False


def encrypt(plain: str) -> str:
    return _box().encrypt(plain.encode()).decode()


def decrypt(sealed: str) -> str:
    """Raises NotConfigured if the stored value cannot be opened with any current key."""
    try:
        return _box().decrypt(sealed.encode()).decode()
    except InvalidToken:
        raise NotConfigured("A stored secret could not be decrypted with TOKEN_ENCRYPTION_KEY") from None
