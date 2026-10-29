"""/admin: moderator queue, actions, audit log and appeals. Moderators and admins only."""

import uuid

from fastapi import APIRouter, Query

import admin_service
from deps import DB, ModUser
from schemas import (
    AppealOut,
    AppealPage,
    AppealResolveIn,
    AuditPage,
    ModActionIn,
    ModActionOut,
    QueueOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/queue", response_model=QueueOut)
async def queue(mod: ModUser, db: DB) -> QueueOut:
    return await admin_service.queue(db)


@router.post("/actions", response_model=ModActionOut, status_code=201)
async def act(data: ModActionIn, mod: ModUser, db: DB) -> ModActionOut:
    return await admin_service.act(db, mod, data)


@router.get("/audit", response_model=AuditPage)
async def audit(
    mod: ModUser, db: DB, cursor: str | None = Query(None, max_length=200)
) -> AuditPage:
    return await admin_service.audit(db, cursor)


@router.get("/appeals", response_model=AppealPage)
async def appeals(
    mod: ModUser, db: DB, cursor: str | None = Query(None, max_length=200)
) -> AppealPage:
    return await admin_service.list_appeals(db, cursor)


@router.post("/appeals/{appeal_id}/resolve", response_model=AppealOut)
async def resolve(appeal_id: uuid.UUID, data: AppealResolveIn, mod: ModUser, db: DB) -> AppealOut:
    return await admin_service.resolve_appeal(db, mod, appeal_id, data.accept, data.note)
