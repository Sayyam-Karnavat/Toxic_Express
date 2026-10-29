"""Shared FastAPI dependencies: auth, roles, rate limiting, CSRF guard, client IP."""

import contextlib
import uuid
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import Depends, Request
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from cache import get_redis, hit_rate_limit
from database import get_db
from errors import AppError, forbidden, unauthorized
from models import Role, User, UserStatus
from security import decode_access_token
from utils import utcnow

DB = Annotated[AsyncSession, Depends(get_db)]

CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "toxic-express"


def client_ip(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Caddy, so request.client is the real client.
    return request.client.host if request.client else "unknown"


def revoked_session_key(session_id: uuid.UUID | str) -> str:
    return f"revoked_sid:{session_id}"


async def _load_user(request: Request, db: AsyncSession, *, required: bool) -> User | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        if required:
            raise unauthorized()
        return None
    payload = decode_access_token(header[7:].strip())
    try:
        if await get_redis().exists(revoked_session_key(payload["sid"])):
            raise unauthorized("Session has been revoked")
    except RedisError:
        pass  # access tokens are short-lived; tolerate a Redis outage
    user = await db.get(User, uuid.UUID(payload["sub"]))
    if user is None or user.status in (UserStatus.banned, UserStatus.deleted):
        raise unauthorized("Account is not active")
    request.state.user_id = user.id
    request.state.session_id = uuid.UUID(payload["sid"])
    return user


async def get_current_user_optional(request: Request, db: DB) -> User | None:
    return await _load_user(request, db, required=False)


async def get_current_user(request: Request, db: DB) -> User:
    user = await _load_user(request, db, required=True)
    assert user is not None
    return user


def is_suspended(user: User) -> bool:
    return user.status == UserStatus.suspended and (
        user.suspended_until is None or user.suspended_until > utcnow()
    )


async def get_active_user(user: Annotated[User, Depends(get_current_user)]) -> User:
    """For write actions: the account must not be suspended and must have finished onboarding."""
    if is_suspended(user):
        raise AppError(
            403,
            "account_suspended",
            "Your account is suspended",
            {"until": user.suspended_until.isoformat() if user.suspended_until else None},
        )
    if not user.onboarded:
        raise AppError(403, "onboarding_required", "Choose a handle to finish setting up")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_current_user_optional)]
ActiveUser = Annotated[User, Depends(get_active_user)]


def require_role(*roles: Role) -> Callable[[User], Awaitable[User]]:
    async def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise forbidden("Moderator access required")
        return user

    return checker


ModUser = Annotated[User, Depends(require_role(Role.mod, Role.admin))]
AdminUser = Annotated[User, Depends(require_role(Role.admin))]


async def require_csrf_header(request: Request) -> None:
    """Cookie-authenticated endpoints require a custom header that cross-site forms cannot set."""
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise forbidden("Missing CSRF header")


def rate_limit(
    name: str, limit: int, window_seconds: int, scope: Literal["ip", "user"] = "ip"
) -> Callable[..., Awaitable[None]]:
    """Dependency factory. scope="user" falls back to IP for anonymous requests."""

    async def dependency(request: Request) -> None:
        subject = f"ip:{client_ip(request)}"
        if scope == "user":
            header = request.headers.get("authorization", "")
            if header.lower().startswith("bearer "):
                with contextlib.suppress(AppError):
                    subject = f"u:{decode_access_token(header[7:].strip())['sub']}"
        result = await hit_rate_limit(f"{name}:{subject}", limit, window_seconds)
        if not result.allowed:
            raise AppError(
                429,
                "rate_limited",
                "Too many requests, slow down",
                {"retry_after": result.retry_after},
                headers={"Retry-After": str(result.retry_after)},
            )

    return dependency
