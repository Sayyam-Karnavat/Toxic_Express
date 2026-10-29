"""/media: presigned uploads and processing status."""

import uuid

from fastapi import APIRouter, Depends

import media_service
from deps import DB, ActiveUser, CurrentUser, rate_limit
from schemas import MediaOut, UploadUrlIn, UploadUrlOut

router = APIRouter(prefix="/media", tags=["media"])


@router.post(
    "/upload-url",
    response_model=UploadUrlOut,
    status_code=201,
    dependencies=[
        Depends(rate_limit("upload", 10, 600, "user")),
        Depends(rate_limit("upload_day", 40, 86400, "user")),
    ],
)
async def upload_url(data: UploadUrlIn, user: ActiveUser, db: DB) -> UploadUrlOut:
    return await media_service.create_upload(db, user, data)


@router.post(
    "/{media_id}/complete",
    response_model=MediaOut,
    dependencies=[Depends(rate_limit("upload_complete", 30, 600, "user"))],
)
async def complete(media_id: uuid.UUID, user: ActiveUser, db: DB) -> MediaOut:
    return media_service.media_out(await media_service.complete_upload(db, user, media_id))


@router.get("/{media_id}", response_model=MediaOut)
async def status(media_id: uuid.UUID, user: CurrentUser, db: DB) -> MediaOut:
    return media_service.media_out(await media_service.get_owned_media(db, user, media_id))
