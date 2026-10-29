"""Google OAuth 2.0 / OpenID Connect: Authorization Code flow with PKCE, verified server-side.

Google tokens never reach the browser. We only keep the stable `sub` claim to link accounts.
"""

import base64
import contextlib
import hashlib
import json
import logging
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import jwt

from cache import get_redis
from config import settings
from errors import AppError
from http_client import get_http_client
from retry import http_retry, raise_for_retryable

logger = logging.getLogger(__name__)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"  # noqa: S105 - URL, not a secret
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ("https://accounts.google.com", "accounts.google.com")
STATE_TTL_SECONDS = 600

Intent = Literal["login", "link"]


class OAuthError(AppError):
    def __init__(self, message: str) -> None:
        super().__init__(400, "oauth_failed", message)


@dataclass(frozen=True)
class GoogleIdentity:
    subject: str
    email: str
    email_verified: bool
    name: str
    picture: str | None


@dataclass(frozen=True)
class FlowResult:
    identity: GoogleIdentity
    intent: Intent
    user_id: uuid.UUID | None


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _state_key(state: str) -> str:
    return f"oauth_state:{state}"


async def start_flow(intent: Intent, user_id: uuid.UUID | None = None) -> str:
    if not settings.google_enabled:
        raise AppError(503, "google_disabled", "Google sign-in is not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    verifier = secrets.token_urlsafe(64)
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    record = {
        "nonce": nonce,
        "verifier": verifier,
        "intent": intent,
        "user_id": str(user_id) if user_id else None,
    }
    await get_redis().set(_state_key(state), json.dumps(record), ex=STATE_TTL_SECONDS)
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "prompt": "select_account",
        "access_type": "online",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


# --- JWKS cache --------------------------------------------------------------------------------

_jwks: dict[str, Any] = {"keys": {}, "expires": 0.0}


async def _fetch_jwks() -> None:
    response: httpx.Response | None = None
    async for attempt in http_retry(attempts=3, max_seconds=8):
        with attempt:
            response = await get_http_client().get(GOOGLE_JWKS_URL)
            raise_for_retryable(response)
    assert response is not None
    max_age = 3600
    for part in response.headers.get("cache-control", "").split(","):
        part = part.strip()
        if part.startswith("max-age="):
            with contextlib.suppress(ValueError):
                max_age = int(part.split("=", 1)[1])
    keys = {k["kid"]: jwt.PyJWK(k) for k in response.json().get("keys", []) if "kid" in k}
    _jwks.update(keys=keys, expires=time.monotonic() + max_age)


async def _signing_key(kid: str) -> jwt.PyJWK:
    if time.monotonic() >= _jwks["expires"] or kid not in _jwks["keys"]:
        await _fetch_jwks()  # also handles Google key rotation
    key = _jwks["keys"].get(kid)
    if key is None:
        raise OAuthError("Unknown Google signing key")
    return key


async def verify_id_token(id_token: str, nonce: str) -> GoogleIdentity:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise OAuthError("Malformed ID token") from exc
    if header.get("alg") != "RS256" or "kid" not in header:
        raise OAuthError("Unexpected ID token algorithm")
    key = await _signing_key(header["kid"])
    try:
        claims = jwt.decode(
            id_token,
            key=key,
            algorithms=["RS256"],
            audience=settings.google_client_id,
            issuer=GOOGLE_ISSUERS,
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise OAuthError("Invalid ID token") from exc
    if not secrets.compare_digest(str(claims.get("nonce", "")), nonce):
        raise OAuthError("ID token nonce mismatch")
    email = str(claims.get("email", "")).lower()
    if not email:
        raise OAuthError("Google account has no email")
    return GoogleIdentity(
        subject=str(claims["sub"]),
        email=email,
        email_verified=bool(claims.get("email_verified")),
        name=str(claims.get("name") or email.split("@")[0])[:50],
        picture=claims.get("picture"),
    )


async def complete_flow(code: str, state: str) -> FlowResult:
    raw = await get_redis().getdel(_state_key(state))  # single use
    if raw is None:
        raise OAuthError("Sign-in session expired, please try again")
    record = json.loads(raw)
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret.get_secret_value(),
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
        "code_verifier": record["verifier"],
    }
    # Authorization codes are single-use: only retry when the request never reached Google.
    response: httpx.Response | None = None
    for attempt in range(3):
        try:
            response = await get_http_client().post(GOOGLE_TOKEN_URL, data=data)
            break
        except (httpx.ConnectError, httpx.ConnectTimeout):
            if attempt == 2:
                raise OAuthError("Could not reach Google, please try again") from None
    assert response is not None
    if response.status_code != 200:
        logger.warning(
            "Google token exchange failed: %s %s", response.status_code, response.text[:200]
        )
        raise OAuthError("Google sign-in failed")
    id_token = response.json().get("id_token")
    if not id_token:
        raise OAuthError("Google did not return an ID token")
    identity = await verify_id_token(id_token, record["nonce"])
    if not identity.email_verified:
        raise OAuthError("Your Google email address is not verified")
    user_id = uuid.UUID(record["user_id"]) if record.get("user_id") else None
    return FlowResult(identity=identity, intent=record["intent"], user_id=user_id)
