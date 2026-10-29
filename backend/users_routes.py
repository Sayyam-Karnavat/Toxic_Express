"""/me and /users/{handle}: own account, settings, sessions, export, public profiles."""

import uuid

from fastapi import APIRouter, Depends, Request
from sqlalchemy import exists, select

import auth_service
import users_service
from deps import DB, ActiveUser, CurrentUser, OptionalUser, rate_limit
from errors import AppError, conflict, not_found
from models import AuthSession, User
from schemas import (
    DeleteAccountIn,
    EmailChangeIn,
    MeOut,
    OkOut,
    OnboardingIn,
    ProfileOut,
    ProfileUpdateIn,
    SessionOut,
    SettingsOut,
    SettingsPatchIn,
)
from security import verify_password
from utils import utcnow

router = APIRouter(tags=["users"])


@router.get("/me", response_model=MeOut)
async def get_me(user: CurrentUser, db: DB) -> MeOut:
    return await users_service.build_me(db, user)


@router.patch(
    "/me",
    response_model=MeOut,
    dependencies=[Depends(rate_limit("profile_update", 30, 3600, "user"))],
)
async def update_me(data: ProfileUpdateIn, user: ActiveUser, db: DB) -> MeOut:
    await users_service.update_profile(db, user, data)
    return await users_service.build_me(db, user)


@router.post(
    "/me/onboarding",
    response_model=MeOut,
    dependencies=[Depends(rate_limit("onboarding", 20, 3600, "user"))],
)
async def onboarding(data: OnboardingIn, user: CurrentUser, db: DB) -> MeOut:
    await users_service.complete_onboarding(db, user, data)
    return await users_service.build_me(db, user)


@router.post(
    "/me/email",
    response_model=MeOut,
    dependencies=[Depends(rate_limit("email_change", 5, 86400, "user"))],
)
async def change_email(data: EmailChangeIn, user: ActiveUser, db: DB) -> MeOut:
    if user.password_hash is not None:
        valid, _ = await verify_password(data.password or "", user.password_hash)
        if not valid:
            raise AppError(400, "invalid_password", "Password is incorrect")
    email = data.email.lower()
    if email != user.email:
        if await db.scalar(select(exists().where(User.email == email))):
            raise conflict("email_taken", "An account with this email already exists")
        user.email = email
        user.email_verified_at = None
        await auth_service.commit_or_conflict(db)
        await auth_service.send_verification_email(user)
    return await users_service.build_me(db, user)


@router.get("/me/settings", response_model=SettingsOut)
async def get_settings(user: CurrentUser, db: DB) -> SettingsOut:
    return await users_service.load_settings(db, user.id)


@router.patch(
    "/me/settings",
    response_model=SettingsOut,
    dependencies=[Depends(rate_limit("settings_update", 60, 3600, "user"))],
)
async def patch_settings(data: SettingsPatchIn, user: CurrentUser, db: DB) -> SettingsOut:
    return await users_service.update_settings(db, user, data)


@router.get("/me/sessions", response_model=list[SessionOut])
async def list_sessions(request: Request, user: CurrentUser, db: DB) -> list[SessionOut]:
    rows = (
        await db.scalars(
            select(AuthSession)
            .where(
                AuthSession.user_id == user.id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > utcnow(),
            )
            .order_by(AuthSession.last_used_at.desc())
        )
    ).all()
    current = getattr(request.state, "session_id", None)
    return [
        SessionOut.model_validate(r).model_copy(update={"current": r.id == current}) for r in rows
    ]


@router.delete("/me/sessions/{session_id}", response_model=OkOut)
async def revoke_session(session_id: uuid.UUID, user: CurrentUser, db: DB) -> OkOut:
    if not await auth_service.revoke_session(db, user.id, session_id):
        raise not_found("Session")
    return OkOut()


@router.get("/me/export", dependencies=[Depends(rate_limit("export", 3, 86400, "user"))])
async def export(user: CurrentUser, db: DB) -> dict:
    return await users_service.export_data(db, user)


@router.delete(
    "/me",
    response_model=OkOut,
    dependencies=[Depends(rate_limit("delete_account", 5, 3600, "user"))],
)
async def delete_me(data: DeleteAccountIn, user: CurrentUser, db: DB) -> OkOut:
    if user.password_hash is not None:
        valid, _ = await verify_password(data.password or "", user.password_hash)
        if not valid:
            raise AppError(400, "invalid_password", "Password is incorrect")
    await users_service.schedule_deletion(db, user)
    from tasks import enqueue

    await enqueue("send_email", "account_deletion", user.email, user.display_name, "")
    return OkOut()


@router.get("/users/{handle}", response_model=ProfileOut)
async def get_profile(handle: str, viewer: OptionalUser, db: DB) -> ProfileOut:
    return await users_service.get_profile(db, handle, viewer)
