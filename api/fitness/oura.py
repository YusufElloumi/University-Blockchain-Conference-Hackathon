"""Connecting a user's Oura account (OAuth 2.0 with PKCE). Connection only: no workouts or heart rate are read yet.

The flow, and why it has three steps:
  1. start     The signed-in web app asks for a sign-in address. We make a random `state` and a PKCE
               secret, store them (state hashed, secret encrypted) against this user, and return
               Oura's authorize address.
  2. callback  Oura sends the browser to OURA_REDIRECT_URI with a one-time code. That request carries
               no Rival login, so we only park the code (encrypted) on the matching state and send the
               browser back to the web app.
  3. complete  The web app, signed in again, hands the state back. Only the user who started the
               attempt can finish it, which binds the Oura account to the right Rival account even if a
               sign-in link is passed to someone else. The code is then swapped for tokens here, on the
               server.

Each attempt expires after STATE_TTL and can be finished once. Tokens are encrypted with
api/secretbox.py, stay on the server, and are never logged or returned to the browser.
Oura docs: https://cloud.ouraring.com/docs/authentication
"""

from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

import config
import db
import secretbox

PROVIDER = "oura"
AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
REVOKE_URL = "https://api.ouraring.com/oauth/revoke"
# The least we need for later workout and heart-rate checks. Nothing else is requested.
SCOPES = ("workout", "heartrate")
STATE_TTL = timedelta(minutes=10)
REFRESH_MARGIN = timedelta(minutes=5)  # refresh a token this long before it runs out
HEADERS = {"User-Agent": "Rival/1.0 (devnet prototype)"}  # Oura rejects requests without one

log = logging.getLogger("loser_buys")
# httpx logs every request address at INFO; the revoke address carries a token, so keep it quiet.
logging.getLogger("httpx").setLevel(logging.WARNING)


class OuraError(Exception):
    """Something the user should see. The message never contains a token or code."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass
class Tokens:
    access: str
    refresh: str | None
    expires_at: datetime | None
    scopes: str | None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(state: str) -> str:
    return hashlib.sha256(state.encode()).hexdigest()


def is_configured() -> bool:
    return bool(config.OURA_CLIENT_ID and config.OURA_CLIENT_SECRET and config.OURA_REDIRECT_URI) and secretbox.is_configured()


def _require_configured() -> None:
    if not is_configured():
        raise OuraError("Connecting Oura isn't available on this server yet.", 503)


def allowed_return(url: str) -> str:
    """The web app page to come back to, if it belongs to one of our web origins (WEB_ORIGIN)."""
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise OuraError("Unknown return address.")
    origin = config.clean_origin(f"{parts.scheme}://{parts.netloc}")
    if origin not in config.WEB_ORIGINS:
        raise OuraError("Unknown return address.")
    return f"{origin}{parts.path or '/'}"


def back_to(return_to: str, **params: str) -> str:
    return f"{return_to}?{urlencode(params)}"


def fallback_return() -> str:
    """Where to send the browser when the attempt can't be identified: the first web origin."""
    return (config.WEB_ORIGINS[0] if config.WEB_ORIGINS else "http://localhost:5173") + "/"


# ---------- 1. start ----------


def start(session: Session, user_id: int, return_to: str) -> str:
    """Records a new attempt for this user and returns Oura's authorize address."""
    _require_configured()
    return_to = allowed_return(return_to)
    # Tidy up: this user's unfinished attempts and everyone's expired ones.
    session.execute(delete(db.OAuthState).where(db.OAuthState.user_id == user_id, db.OAuthState.used_at.is_(None)))
    session.execute(delete(db.OAuthState).where(db.OAuthState.expires_at < _now() - timedelta(days=1)))

    state = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)  # 86 characters; PKCE allows 43-128
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    session.add(db.OAuthState(
        state_hash=_hash(state), user_id=user_id, provider=PROVIDER, return_to=return_to,
        code_verifier_enc=secretbox.encrypt(verifier), expires_at=_now() + STATE_TTL,
    ))
    session.commit()
    return AUTHORIZE_URL + "?" + urlencode({
        "response_type": "code",
        "client_id": config.OURA_CLIENT_ID,
        "redirect_uri": config.OURA_REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })


# ---------- 2. callback (no Rival login on this request) ----------


def callback(session: Session, state: str | None, code: str | None, error: str | None) -> str:
    """Parks Oura's code on the attempt and returns where to send the browser next."""
    row = session.scalar(select(db.OAuthState).where(db.OAuthState.state_hash == _hash(state))) if state else None
    if row is None or row.provider != PROVIDER:
        return back_to(fallback_return(), oura="error", reason="unknown")
    if row.used_at is not None or row.returned_at is not None or db.utc(row.expires_at) < _now():
        return back_to(row.return_to, oura="error", reason="expired")
    if error or not code:
        row.used_at = _now()
        row.code_verifier_enc = None
        session.commit()
        return back_to(row.return_to, oura="cancelled" if error == "access_denied" else "error")
    # Only one callback may land for an attempt (a replayed redirect finds returned_at already set).
    landed = session.execute(
        update(db.OAuthState)
        .where(db.OAuthState.id == row.id, db.OAuthState.returned_at.is_(None))
        .values(returned_at=_now(), code_enc=secretbox.encrypt(code))
    )
    session.commit()
    if landed.rowcount != 1:
        return back_to(row.return_to, oura="error", reason="expired")
    return back_to(row.return_to, oura="finish", oura_state=state)


# ---------- 3. complete (signed in) ----------


def complete(session: Session, user_id: int, state: str) -> None:
    """Finishes the attempt for the signed-in user: swaps the code for tokens and saves them encrypted."""
    _require_configured()
    row = session.scalar(select(db.OAuthState).where(db.OAuthState.state_hash == _hash(state or "")))
    if row is None or row.provider != PROVIDER:
        raise OuraError("This Oura sign-in link isn't valid. Try connecting again.")
    if row.user_id != user_id:
        # Started by a different Rival account: burn it so nobody can finish it.
        _burn(session, row)
        raise OuraError("This Oura sign-in was started from a different Rival account. Try connecting again.", 403)
    if row.used_at is not None or row.code_enc is None:
        raise OuraError("This Oura sign-in was already used. Try connecting again.", 409)
    if db.utc(row.expires_at) < _now():
        _burn(session, row)
        raise OuraError("This Oura sign-in expired. Try connecting again.", 410)
    # Claim it: only one request can move used_at from empty to set.
    claimed = session.execute(
        update(db.OAuthState).where(db.OAuthState.id == row.id, db.OAuthState.used_at.is_(None)).values(used_at=_now())
    )
    session.commit()
    if claimed.rowcount != 1:
        raise OuraError("This Oura sign-in was already used. Try connecting again.", 409)

    code = secretbox.decrypt(row.code_enc)
    verifier = secretbox.decrypt(row.code_verifier_enc) if row.code_verifier_enc else None
    _burn(session, row)  # the code and verifier are never needed again
    tokens = _token_request({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": config.OURA_REDIRECT_URI,
        **({"code_verifier": verifier} if verifier else {}),
    })
    _save(session, user_id, tokens)


def _burn(session: Session, row: db.OAuthState) -> None:
    session.execute(
        update(db.OAuthState).where(db.OAuthState.id == row.id)
        .values(used_at=row.used_at or _now(), code_enc=None, code_verifier_enc=None)
    )
    session.commit()


# ---------- tokens ----------


def _token_request(form: dict) -> Tokens:
    """POSTs to Oura's token endpoint. Errors are reported without the response body or any token."""
    try:
        response = httpx.post(
            TOKEN_URL,
            data={**form, "client_id": config.OURA_CLIENT_ID, "client_secret": config.OURA_CLIENT_SECRET},
            headers=HEADERS,
            timeout=15,
        )
    except httpx.HTTPError as e:
        log.warning("Oura token request failed: %s", type(e).__name__)
        raise OuraError("Couldn't reach Oura. Try again in a moment.", 502) from None
    if response.status_code in (400, 401):
        log.warning("Oura token request refused (HTTP %s, grant %s)", response.status_code, form.get("grant_type"))
        raise OuraError("Oura didn't accept the sign-in. Try connecting again.", 400)
    if response.status_code != 200:
        log.warning("Oura token request failed (HTTP %s)", response.status_code)
        raise OuraError("Oura had a problem. Try again in a moment.", 502)
    data = response.json()
    if not data.get("access_token"):
        raise OuraError("Oura sent an unexpected reply. Try connecting again.", 502)
    expires_in = data.get("expires_in")
    return Tokens(
        access=data["access_token"],
        refresh=data.get("refresh_token"),
        expires_at=_now() + timedelta(seconds=int(expires_in)) if expires_in else None,
        scopes=data.get("scope"),
    )


def _save(session: Session, user_id: int, tokens: Tokens) -> None:
    connection = session.scalar(
        select(db.FitnessConnection).where(db.FitnessConnection.user_id == user_id, db.FitnessConnection.provider == PROVIDER)
    )
    if connection is None:
        connection = db.FitnessConnection(user_id=user_id, provider=PROVIDER)
        session.add(connection)
        connection.connected_at = _now()
    connection.access_token_enc = secretbox.encrypt(tokens.access)
    if tokens.refresh:  # Oura rotates refresh tokens: always keep the newest
        connection.refresh_token_enc = secretbox.encrypt(tokens.refresh)
    connection.token_expires_at = tokens.expires_at
    # Oura's token reply may not list scopes; then record what we asked for.
    connection.scopes = tokens.scopes or connection.scopes or " ".join(SCOPES)
    session.commit()


def _connection(session: Session, user_id: int, lock: bool = False) -> db.FitnessConnection | None:
    query = select(db.FitnessConnection).where(
        db.FitnessConnection.user_id == user_id, db.FitnessConnection.provider == PROVIDER
    )
    return session.scalar(query.with_for_update() if lock else query)


def access_token(session: Session, user_id: int) -> str:
    """A valid access token for this user, refreshed first if it is about to run out.

    For future workout and heart-rate reads; nothing calls Oura's data endpoints yet.
    """
    _require_configured()
    # Lock the row (Postgres) so two requests can't spend the single-use refresh token at once.
    connection = _connection(session, user_id, lock=True)
    if connection is None or not connection.access_token_enc:
        raise OuraError("Oura isn't connected.", 404)
    expires = db.utc(connection.token_expires_at) if connection.token_expires_at else None
    if expires is None or expires - REFRESH_MARGIN > _now():
        return secretbox.decrypt(connection.access_token_enc)
    if not connection.refresh_token_enc:
        raise OuraError("Your Oura connection expired. Connect it again.", 401)
    try:
        tokens = _token_request({"grant_type": "refresh_token", "refresh_token": secretbox.decrypt(connection.refresh_token_enc)})
    except OuraError as e:
        if e.status == 400:  # refresh token refused: the link is dead, so forget it
            session.delete(connection)
            session.commit()
            raise OuraError("Your Oura connection expired. Connect it again.", 401) from None
        raise
    _save(session, user_id, tokens)
    return tokens.access


# ---------- status and disconnect ----------


def granted_scopes(raw: str | None) -> set[str]:
    """Permission names as we ask for them. Oura's newer sign-in server reports them with a prefix
    ("extapi:workout"), the older one without ("workout"); either way we compare the plain name.
    The raw value is stored unchanged."""
    names = (raw or "").replace(",", " ").split()
    return {name.removeprefix("extapi:") for name in names}


def status(session: Session, user_id: int) -> dict:
    connection = _connection(session, user_id)
    granted = granted_scopes(connection.scopes) if connection else set()
    return {
        "available": is_configured(),
        "connected": connection is not None,
        "connected_at": db.utc(connection.connected_at).isoformat() if connection else None,
        "missing_permissions": [s for s in SCOPES if s not in granted] if connection and connection.scopes else [],
    }


def disconnect(session: Session, user_id: int) -> bool:
    """Revokes access at Oura where possible and deletes the stored tokens. Returns whether Oura confirmed."""
    connection = _connection(session, user_id)
    if connection is None:
        return False
    revoked = False
    try:
        token = access_token(session, user_id) if is_configured() else None
    except (OuraError, secretbox.NotConfigured):
        token = None
    if token:
        try:
            response = httpx.get(REVOKE_URL, params={"access_token": token}, headers=HEADERS, timeout=15)
            revoked = response.status_code == 200
            if not revoked:
                log.warning("Oura revoke answered HTTP %s", response.status_code)
        except httpx.HTTPError as e:
            log.warning("Oura revoke failed: %s", type(e).__name__)
    # Delete whatever is left (access_token may already have removed a dead link).
    session.execute(
        delete(db.FitnessConnection).where(db.FitnessConnection.user_id == user_id, db.FitnessConnection.provider == PROVIDER)
    )
    session.execute(delete(db.OAuthState).where(db.OAuthState.user_id == user_id, db.OAuthState.provider == PROVIDER))
    session.commit()
    return revoked
