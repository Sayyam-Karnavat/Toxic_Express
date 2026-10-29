"""/reports and /appeals (user side of trust & safety)."""

from fastapi import APIRouter, Depends

import admin_service
import reports_service
from deps import DB, CurrentUser, rate_limit
from schemas import AppealIn, AppealOut, ModActionOut, OkOut, ReportIn

router = APIRouter(tags=["safety"])


@router.post(
    "/reports",
    response_model=OkOut,
    status_code=201,
    dependencies=[Depends(rate_limit("report", 20, 3600, "user"))],
)
async def report(data: ReportIn, user: CurrentUser, db: DB) -> OkOut:
    await reports_service.create_report(db, user, data)
    return OkOut()


@router.get("/me/moderation-actions", response_model=list[ModActionOut])
async def my_actions(user: CurrentUser, db: DB) -> list[ModActionOut]:
    return await admin_service.my_actions(db, user)


@router.post(
    "/appeals",
    response_model=AppealOut,
    status_code=201,
    dependencies=[Depends(rate_limit("appeal", 5, 86400, "user"))],
)
async def appeal(data: AppealIn, user: CurrentUser, db: DB) -> AppealOut:
    return await admin_service.create_appeal(db, user, data)
