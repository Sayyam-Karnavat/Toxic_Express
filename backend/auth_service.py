"""Authentication flows: signup, login, refresh rotation, logout, email verification, password
reset and Google sign-in account resolution."""

import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cache import get_redis, hit_rate_limit
from config import settings
from deps import client_ip, revoked_session_key
from errors import AppError, bad_request, conflict, unauthorized
from models import AuthSession, OAuthAccount, User, UserSettings, UserStatus
from oauth import GoogleIdentity
from schemas import RESERVED_HANDLES, SignupIn, TokenOut
from security import (
    create_access_token,
    hash_password,
    hash_token,
    new_opaque_token,
    new_refresh_token,
    parse_refresh_token,
    set_refresh_cookie,
    tokens_equal,
    validate_password_strength,
    verify_password,
)
from tasks import enqueue
from users_service import build_me
from utils import utcnow, uuid7

logger = logging.getLogger(__name__)

MAX_SESSIONS_PER_USER = 20
REFRESH_REUSE_GRACE = timedelta(seconds=30)


# --- Sessions & tokens -------------------------------------------------------------------------


async def _create_session(db: AsyncSession, user: User, request: Request) -> tuple[uuid.UUID, str]:
    sid = uuid7()
    token, token_hash = new_refresh_token(sid)
    db.add(
        AuthSession(
            id=sid,
            user_id=user.id,
            token_hash=token_hash,
            user_agent=(request.headers.get("user-agent") or "")[:255],
            ip=client_ip(request),
            expires_at=utcnow() + timedelta(days=settings.refresh_token_ttl_days),
        )
    )
    await db.flush()
    # Cap concurrent sessions: revoke the oldest beyond the limit.
    keep = (
        select(AuthSession.id)
        .where(AuthSession.user_id == user.id, AuthSession.revoked_at.is_(None))
        .order_by(AuthSession.created_at.desc())
        .limit(MAX_SESSIONS_PER_USER)
    )
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
            AuthSession.id.not_in(keep),
        )
        .values(revoked_at=utcnow())
    )
    return sid, token


async def _token_out(db: AsyncSession, user: User, sid: uuid.UUID) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user.id, sid, user.role.value),
        expires_in=settings.access_token_ttl_minutes * 60,
        user=await build_me(db, user),
    )


async def _mark_revoked(*session_ids: uuid.UUID) -> None:
    if not session_ids:
        return
    ttl = settings.access_token_ttl_minutes * 60 + 60
    async with get_redis().pipeline(transaction=False) as pipe:
        for sid in session_ids:
            pipe.set(revoked_session_key(sid), "1", ex=ttl)
        await pipe.execute()


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Caller commits. Access tokens of these sessions are rejected immediately via Redis."""
    revoked = (
        await db.scalars(
            update(AuthSession)
            .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=utcnow())
            .returning(AuthSession.id)
        )
    ).all()
    await _mark_revoked(*revoked)


async def revoke_session(db: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID) -> bool:
    result = await db.scalar(
        update(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=utcnow())
        .returning(AuthSession.id)
    )
    await db.commit()
    if result:
        await _mark_revoked(result)
    return result is not None


async def _reactivate_if_pending_deletion(db: AsyncSession, user: User) -> None:
    """Logging in during the deletion grace period cancels the deletion."""
    if (
        user.status == UserStatus.deleted
        and user.deletion_scheduled_at
        and (user.deletion_scheduled_at > utcnow())
    ):
        from users_service import set_author_hidden

        user.status = UserStatus.active
        user.deletion_scheduled_at = None
        await set_author_hidden(db, user.id, False)


def _ensure_can_login(user: User) -> None:
    if user.status == UserStatus.banned:
        raise AppError(403, "account_banned", "This account has been banned")
    if user.status == UserStatus.deleted:
        raise unauthorized("Invalid email or password")


async def commit_or_conflict(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        text = str(exc.orig)
        if "users_email" in text:
            raise conflict("email_taken", "An account with this email already exists") from exc
        if "users_handle" in text:
            raise conflict("handle_taken", "That handle is taken") from exc
        raise


# --- Signup / login / refresh / logout ---------------------------------------------------------


async def signup(
    db: AsyncSession, data: SignupIn, request: Request, response: Response
) -> TokenOut:
    email = data.email.lower()
    validate_password_strength(data.password, email=email, handle=data.handle)
    if await db.scalar(select(exists().where(User.email == email))):
        raise conflict("email_taken", "An account with this email already exists")
    if await db.scalar(select(exists().where(User.handle == data.handle))):
        raise conflict("handle_taken", "That handle is taken")
    user = User(
        id=uuid7(),
        email=email,
        handle=data.handle,
        display_name=data.display_name,
        password_hash=await hash_password(data.password),
        last_login_at=utcnow(),
    )
    db.add(user)
    db.add(UserSettings(user_id=user.id))
    await db.flush()
    sid, refresh = await _create_session(db, user, request)
    await commit_or_conflict(db)
    await send_verification_email(user)
    set_refresh_cookie(response, refresh)
    return await _token_out(db, user, sid)


async def login(
    db: AsyncSession, email: str, password: str, request: Request, response: Response
) -> TokenOut:
    email = email.lower()
    limit = await hit_rate_limit(f"login_email:{email}", 10, 900)
    if not limit.allowed:
        raise AppError(
            429,
            "rate_limited",
            "Too many login attempts, try again later",
            {"retry_after": limit.retry_after},
            headers={"Retry-After": str(limit.retry_after)},
        )
    user = await db.scalar(select(User).where(User.email == email))
    valid, new_hash = await verify_password(password, user.password_hash if user else None)
    if user is None or not valid:
        raise unauthorized("Invalid email or password")
    await _reactivate_if_pending_deletion(db, user)
    _ensure_can_login(user)
    if new_hash:
        user.password_hash = new_hash
    user.last_login_at = utcnow()
    sid, refresh = await _create_session(db, user, request)
    await db.commit()
    set_refresh_cookie(response, refresh)
    return await _token_out(db, user, sid)


async def refresh(db: AsyncSession, cookie: str | None, response: Response) -> TokenOut:
    sid, presented = parse_refresh_token(cookie)
    session = await db.scalar(select(AuthSession).where(AuthSession.id == sid).with_for_update())
    now = utcnow()
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        raise unauthorized("Session expired, please log in again")
    user = await db.get(User, session.user_id)
    if user is None or user.status in (UserStatus.banned, UserStatus.deleted):
        session.revoked_at = now
        await db.commit()
        raise unauthorized("Account is not active")

    if tokens_equal(presented, session.token_hash):
        token, token_hash = new_refresh_token(sid)
        session.prev_token_hash = session.token_hash
        session.token_hash = token_hash
        session.rotated_at = now
        session.last_used_at = now
        await db.commit()
        set_refresh_cookie(response, token)
    elif (
        tokens_equal(presented, session.prev_token_hash)
        and session.rotated_at is not None
        and now - session.rotated_at < REFRESH_REUSE_GRACE
    ):
        # Concurrent refresh from another tab: the browser already holds the newest cookie.
        await db.commit()
    else:
        # A rotated-out token was replayed: assume theft and kill the session.
        logger.warning("refresh token reuse detected for session %s", sid)
        session.revoked_at = now
        await db.commit()
        await _mark_revoked(sid)
        raise unauthorized("Session expired, please log in again")
    return await _token_out(db, user, sid)


async def logout(db: AsyncSession, cookie: str | None, access_sid: uuid.UUID | None) -> None:
    sids: set[uuid.UUID] = set()
    if access_sid:
        sids.add(access_sid)
    if cookie:
        try:
            sid, presented = parse_refresh_token(cookie)
            session = await db.get(AuthSession, sid)
            if session and (
                tokens_equal(presented, session.token_hash)
                or tokens_equal(presented, session.prev_token_hash)
            ):
                sids.add(sid)
        except AppError:
            pass
    if not sids:
        return
    await db.execute(
        update(AuthSession)
        .where(AuthSession.id.in_(sids), AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    await db.commit()
    await _mark_revoked(*sids)


# --- Email verification & password reset ------------------------------------------------------


async def send_verification_email(user: User) -> None:
    if user.email_verified_at is not None:
        return
    token = new_opaque_token()
    value = json.dumps({"user_id": str(user.id), "email": user.email})
    await get_redis().set(
        f"email_verify:{hash_token(token)}", value, ex=settings.email_verify_ttl_hours * 3600
    )
    await enqueue("send_email", "verification", user.email, user.display_name, token)


async def verify_email(db: AsyncSession, token: str) -> None:
    raw = await get_redis().getdel(f"email_verify:{hash_token(token)}")
    if raw is None:
        raise bad_request("invalid_token", "This verification link is invalid or has expired")
    data = json.loads(raw)
    user = await db.get(User, uuid.UUID(data["user_id"]))
    if user is None or user.email != data["email"]:
        raise bad_request("invalid_token", "This verification link is no longer valid")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        await db.commit()


async def forgot_password(db: AsyncSession, email: str) -> None:
    """Always succeeds from the caller's view, so it cannot be used to discover accounts."""
    email = email.lower()
    if not (await hit_rate_limit(f"pwreset_email:{email}", 3, 3600)).allowed:
        return
    user = await db.scalar(select(User).where(User.email == email))
    if user is None or user.status in (UserStatus.banned, UserStatus.deleted):
        return
    token = new_opaque_token()
    await get_redis().set(
        f"pwreset:{hash_token(token)}", str(user.id), ex=settings.password_reset_ttl_minutes * 60
    )
    await enqueue("send_email", "password_reset", user.email, user.display_name, token)


async def reset_password(db: AsyncSession, token: str, password: str) -> None:
    raw = await get_redis().getdel(f"pwreset:{hash_token(token)}")
    if raw is None:
        raise bad_request("invalid_token", "This reset link is invalid or has expired")
    user = await db.get(User, uuid.UUID(raw.decode() if isinstance(raw, bytes) else raw))
    if user is None or user.status in (UserStatus.banned, UserStatus.deleted):
        raise bad_request("invalid_token", "This reset link is no longer valid")
    validate_password_strength(password, email=user.email, handle=user.handle)
    user.password_hash = await hash_password(password)
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()  # the reset link proved ownership of the inbox
    await revoke_all_sessions(db, user.id)
    await db.commit()


async def set_password(db: AsyncSession, user: User, password: str, current: str | None) -> None:
    if user.password_hash is not None:
        valid, _ = await verify_password(current or "", user.password_hash)
        if not valid:
            raise AppError(400, "invalid_password", "Current password is incorrect")
    validate_password_strength(password, email=user.email, handle=user.handle)
    user.password_hash = await hash_password(password)
    await db.commit()


# --- Google -------------------------------------------------------------------------------------


@dataclass
class GoogleLoginResult:
    user: User
    is_new: bool


async def _generate_handle(db: AsyncSession, email: str) -> str:
    base = re.sub(r"[^a-z0-9_]", "", email.split("@")[0].lower())[:20]
    if len(base) < 3 or base in RESERVED_HANDLES or base.startswith("deleted_"):
        base = "ranter"
    candidates = [f"{base}_{secrets.randbelow(9000) + 1000}" for _ in range(8)]
    taken = set((await db.scalars(select(User.handle).where(User.handle.in_(candidates)))).all())
    for candidate in candidates:
        if candidate not in taken:
            return candidate
    return f"ranter_{secrets.token_hex(6)}"


async def google_link(db: AsyncSession, identity: GoogleIdentity, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None or user.status in (UserStatus.banned, UserStatus.deleted):
        raise AppError(400, "oauth_failed", "Account not available")
    existing = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google", OAuthAccount.subject == identity.subject
        )
    )
    if existing is not None:
        if existing.user_id != user.id:
            raise AppError(409, "google_in_use", "This Google account is linked to another user")
        return user
    if await db.scalar(
        select(exists().where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"))
    ):
        raise AppError(409, "google_already_linked", "Unlink your current Google account first")
    db.add(
        OAuthAccount(
            user_id=user.id, provider="google", subject=identity.subject, email=identity.email
        )
    )
    await db.commit()
    return user


async def google_login(
    db: AsyncSession, identity: GoogleIdentity, request: Request, response: Response
) -> GoogleLoginResult:
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == "google", OAuthAccount.subject == identity.subject
        )
    )
    is_new = False
    if account is not None:
        user = await db.get(User, account.user_id)
        assert user is not None
    else:
        user = await db.scalar(select(User).where(User.email == identity.email))
        if user is not None:
            if user.email_verified_at is None:
                # Pre-account-hijacking defence: someone may have registered this email without
                # owning it. Google proved ownership, so drop the unverified password + sessions.
                user.password_hash = None
                user.email_verified_at = utcnow()
                await revoke_all_sessions(db, user.id)
        else:
            user = User(
                id=uuid7(),
                email=identity.email,
                email_verified_at=utcnow(),
                handle=await _generate_handle(db, identity.email),
                display_name=identity.name or "New ranter",
                onboarded=False,
            )
            db.add(user)
            db.add(UserSettings(user_id=user.id))
            await db.flush()  # user row must exist before the oauth_accounts FK row
            is_new = True
        db.add(
            OAuthAccount(
                user_id=user.id, provider="google", subject=identity.subject, email=identity.email
            )
        )
    await _reactivate_if_pending_deletion(db, user)
    _ensure_can_login(user)
    user.last_login_at = utcnow()
    await db.flush()
    _, refresh_token = await _create_session(db, user, request)
    await commit_or_conflict(db)
    set_refresh_cookie(response, refresh_token)
    if is_new and identity.picture:
        await enqueue("import_avatar", str(user.id), identity.picture)
    return GoogleLoginResult(user=user, is_new=is_new or not user.onboarded)


async def google_unlink(db: AsyncSession, user: User) -> None:
    if user.password_hash is None:
        raise AppError(400, "password_required", "Set a password before unlinking Google")
    account = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id, OAuthAccount.provider == "google"
        )
    )
    if account is None:
        raise AppError(404, "not_found", "No Google account linked")
    await db.delete(account)
    await db.commit()
