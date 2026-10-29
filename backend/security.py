"""Password hashing, JWT access tokens, rotating refresh tokens and the refresh cookie."""

import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from typing import Any

import anyio
import jwt
from fastapi import Response
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from config import settings
from errors import bad_request, unauthorized
from utils import utcnow

REFRESH_COOKIE = "te_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
JWT_ALGORITHM = "HS256"
JWT_ISSUER = "toxic-express"

_hasher = PasswordHash((Argon2Hasher(),))
_dummy_hash: str | None = None


# --- Passwords ---------------------------------------------------------------------------------


def validate_password_strength(password: str, *, email: str = "", handle: str = "") -> None:
    if not 10 <= len(password) <= 128:
        raise bad_request("weak_password", "Password must be 10-128 characters long")
    lowered = password.lower()
    if len(set(password)) < 5:
        raise bad_request("weak_password", "Password is too repetitive")
    for value in (email.split("@")[0], handle):
        if value and len(value) >= 4 and value.lower() in lowered:
            raise bad_request("weak_password", "Password must not contain your email or handle")


async def hash_password(password: str) -> str:
    # Argon2 is deliberately slow; keep it off the event loop.
    return await anyio.to_thread.run_sync(_hasher.hash, password)


async def verify_password(password: str, password_hash: str | None) -> tuple[bool, str | None]:
    """Returns (valid, new_hash_if_rehash_needed). Constant-ish time when no hash exists."""
    global _dummy_hash
    if password_hash is None:
        if _dummy_hash is None:
            _dummy_hash = await hash_password(secrets.token_urlsafe(16))
        await anyio.to_thread.run_sync(_hasher.verify_and_update, password, _dummy_hash)
        return False, None
    return await anyio.to_thread.run_sync(_hasher.verify_and_update, password, password_hash)


# --- Opaque tokens -----------------------------------------------------------------------------


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_opaque_token() -> str:
    return secrets.token_urlsafe(32)


def new_refresh_token(session_id: uuid.UUID) -> tuple[str, str]:
    secret = new_opaque_token()
    return f"{session_id}.{secret}", hash_token(secret)


def parse_refresh_token(token: str | None) -> tuple[uuid.UUID, str]:
    if not token or "." not in token:
        raise unauthorized("Missing or malformed refresh token")
    sid, secret = token.split(".", 1)
    try:
        return uuid.UUID(sid), hash_token(secret)
    except ValueError as exc:
        raise unauthorized("Malformed refresh token") from exc


def tokens_equal(a: str | None, b: str | None) -> bool:
    return a is not None and b is not None and hmac.compare_digest(a, b)


# --- JWT access tokens -------------------------------------------------------------------------


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID, role: str) -> str:
    now = utcnow()
    payload = {
        "sub": str(user_id),
        "sid": str(session_id),
        "role": role,
        "typ": "access",
        "iss": JWT_ISSUER,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_ttl_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret.get_secret_value(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            algorithms=[JWT_ALGORITHM],
            issuer=JWT_ISSUER,
            options={"require": ["sub", "sid", "exp", "iat", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise unauthorized("Access token expired") from exc
    except jwt.PyJWTError as exc:
        raise unauthorized("Invalid access token") from exc
    if payload.get("typ") != "access":
        raise unauthorized("Invalid access token")
    return payload


# --- Refresh cookie ----------------------------------------------------------------------------


def set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        token,
        max_age=settings.refresh_token_ttl_days * 86400,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
