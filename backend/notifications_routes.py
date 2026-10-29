"""/notifications."""

from fastapi import APIRouter, Query

import notifications_service
from deps import DB, CurrentUser
from schemas import MarkReadIn, NotificationPage, OkOut, UnreadCountOut

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=NotificationPage)
async def list_notifications(
    user: CurrentUser, db: DB, cursor: str | None = Query(None, max_length=200)
) -> NotificationPage:
    return await notifications_service.list_notifications(db, user.id, cursor)


@router.get("/unread-count", response_model=UnreadCountOut)
async def unread(user: CurrentUser, db: DB) -> UnreadCountOut:
    return UnreadCountOut(unread=await notifications_service.unread_count(db, user.id))


@router.post("/read", response_model=OkOut)
async def mark_read(data: MarkReadIn, user: CurrentUser, db: DB) -> OkOut:
    await notifications_service.mark_read(db, user.id, data.ids, data.all)
    return OkOut()
