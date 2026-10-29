"""/auth/*: email+password auth, refresh rotation, email verification, password reset, Google."""

import logging
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

import auth_service
import oauth
from config import settings
from deps import DB, CurrentUser, rate_limit, require_csrf_header
from errors import AppError
from schemas import (
    AuthUrlOut,
    EmailIn,
    LoginIn,
    OkOut,
    ResetPasswordIn,
    SetPasswordIn,
    SignupIn,
    TokenIn,
    TokenOut,
)
from security import REFRESH_COOKIE, clear_refresh_cookie, decode_access_token

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

RefreshCookie = Annotated[str | None, Cookie(alias=REFRESH_COOKIE)]


@router.post(
    "/signup",
    response_model=TokenOut,
    status_code=201,
    dependencies=[Depends(rate_limit("signup", 5, 3600))],
)
async def signup(data: SignupIn, request: Request, response: Response, db: DB) -> TokenOut:
    return await auth_service.signup(db, data, request, response)


@router.post(
    "/login", response_model=TokenOut, dependencies=[Depends(rate_limit("login", 20, 900))]
)
async def login(data: LoginIn, request: Request, response: Response, db: DB) -> TokenOut:
    return await auth_service.login(db, data.email, data.password, request, response)


@router.post(
    "/refresh",
    response_model=TokenOut,
    dependencies=[Depends(require_csrf_header), Depends(rate_limit("refresh", 60, 60))],
)
async def refresh(
    response: Response, db: DB, cookie: RefreshCookie = None
) -> TokenOut | JSONResponse:
    try:
        return await auth_service.refresh(db, cookie, response)
    except AppError as exc:
        if exc.status_code != 401:
            raise
        failed = JSONResponse(
            {"error": {"code": exc.code, "message": exc.message, "details": None}}, 401
        )
        clear_refresh_cookie(failed)
        return failed


@router.post("/logout", response_model=OkOut, dependencies=[Depends(require_csrf_header)])
async def logout(
    request: Request, response: Response, db: DB, cookie: RefreshCookie = None
) -> OkOut:
    access_sid = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            import uuid

            access_sid = uuid.UUID(decode_access_token(header[7:].strip())["sid"])
        except AppError:
            pass
    await auth_service.logout(db, cookie, access_sid)
    clear_refresh_cookie(response)
    return OkOut()


@router.post("/logout-all", response_model=OkOut)
async def logout_all(user: CurrentUser, response: Response, db: DB) -> OkOut:
    await auth_service.revoke_all_sessions(db, user.id)
    await db.commit()
    clear_refresh_cookie(response)
    return OkOut()


@router.post(
    "/verify-email",
    response_model=OkOut,
    dependencies=[Depends(rate_limit("verify_email", 20, 3600))],
)
async def verify_email(data: TokenIn, db: DB) -> OkOut:
    await auth_service.verify_email(db, data.token)
    return OkOut()


@router.post(
    "/resend-verification",
    response_model=OkOut,
    dependencies=[Depends(rate_limit("resend_verification", 3, 3600, "user"))],
)
async def resend_verification(user: CurrentUser) -> OkOut:
    await auth_service.send_verification_email(user)
    return OkOut()


@router.post(
    "/forgot-password",
    response_model=OkOut,
    status_code=202,
    dependencies=[Depends(rate_limit("forgot_password", 5, 3600))],
)
async def forgot_password(data: EmailIn, db: DB) -> OkOut:
    await auth_service.forgot_password(db, data.email)
    return OkOut()


@router.post(
    "/reset-password",
    response_model=OkOut,
    dependencies=[Depends(rate_limit("reset_password", 10, 3600))],
)
async def reset_password(data: ResetPasswordIn, db: DB) -> OkOut:
    await auth_service.reset_password(db, data.token, data.password)
    return OkOut()


@router.post(
    "/password",
    response_model=OkOut,
    dependencies=[Depends(rate_limit("set_password", 10, 3600, "user"))],
)
async def set_password(data: SetPasswordIn, user: CurrentUser, db: DB) -> OkOut:
    await auth_service.set_password(db, user, data.password, data.current_password)
    return OkOut()


# --- Google -------------------------------------------------------------------------------------


@router.get("/google/login", dependencies=[Depends(rate_limit("google_login", 20, 60))])
async def google_login_start() -> RedirectResponse:
    return RedirectResponse(await oauth.start_flow("login"), status_code=302)


@router.post(
    "/google/link-url",
    response_model=AuthUrlOut,
    dependencies=[Depends(rate_limit("google_link", 10, 3600, "user"))],
)
async def google_link_url(user: CurrentUser) -> AuthUrlOut:
    return AuthUrlOut(url=await oauth.start_flow("link", user.id))


@router.delete("/google", response_model=OkOut)
async def google_unlink(user: CurrentUser, db: DB) -> OkOut:
    await auth_service.google_unlink(db, user)
    return OkOut()


def _frontend_redirect(path: str, **params: str) -> RedirectResponse:
    query = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(f"{settings.frontend_url}{path}{query}", status_code=302)


@router.get(
    "/google/callback",
    include_in_schema=False,
    dependencies=[Depends(rate_limit("google_callback", 30, 60))],
)
async def google_callback(
    request: Request,
    db: DB,
    code: Annotated[str | None, Query(max_length=2048)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=256)] = None,
) -> RedirectResponse:
    if error or not code or not state:
        return _frontend_redirect("/login", error="google_cancelled")
    try:
        flow = await oauth.complete_flow(code, state)
        if flow.intent == "link":
            assert flow.user_id is not None
            await auth_service.google_link(db, flow.identity, flow.user_id)
            return _frontend_redirect("/settings/account", linked="google")
        response = _frontend_redirect("/auth/callback")
        result = await auth_service.google_login(db, flow.identity, request, response)
        if result.is_new:
            response.headers["location"] = f"{settings.frontend_url}/auth/callback?new=1"
        return response
    except AppError as exc:
        logger.info("Google sign-in failed: %s", exc.code)
        return _frontend_redirect("/login", error=exc.code)
