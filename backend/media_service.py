"""Media uploads: presigned URLs, completion, background processing and cleanup."""

import logging
import uuid
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

import moderation
import storage
from config import settings
from database import SessionLocal
from errors import AppError, bad_request, not_found
from media_processing import (
    MediaRejectedError,
    ProcessedMedia,
    limits_for,
    new_workdir,
    process_image,
    process_video,
    upload_variants,
)
from models import Media, MediaKind, MediaPurpose, MediaState, User
from safe_fetch import BlockedURLError, safe_get
from schemas import MediaOut, UploadUrlIn, UploadUrlOut
from utils import utcnow, uuid7

logger = logging.getLogger(__name__)

MAX_PENDING_UPLOADS = 10


def raw_key(media: Media) -> str:
    return f"raw/{media.owner_id}/{media.id}"


def media_out(media: Media) -> MediaOut:
    return MediaOut(
        id=media.id,
        kind=media.kind,
        purpose=media.purpose,
        state=media.state,
        urls=storage.public_urls(media.variants) if media.state == MediaState.ready else {},
        width=media.width,
        height=media.height,
        duration_seconds=media.duration_seconds,
        reject_reason=media.reject_reason,
    )


async def create_upload(db: AsyncSession, user: User, data: UploadUrlIn) -> UploadUrlOut:
    if settings.media_require_verified_email and user.email_verified_at is None:
        raise AppError(403, "email_unverified", "Verify your email before uploading media")
    min_age = timedelta(hours=settings.media_min_account_age_hours)
    if data.purpose == MediaPurpose.post and utcnow() - user.created_at < min_age:
        raise AppError(403, "account_too_new", "New accounts can post media after 24 hours")
    if data.purpose != MediaPurpose.post and data.kind != MediaKind.image:
        raise bad_request("invalid_media", "Avatars and covers must be images")
    allowed_mimes, max_bytes = limits_for(data.kind)
    if data.mime not in allowed_mimes:
        raise bad_request("unsupported_type", f"Allowed types: {', '.join(sorted(allowed_mimes))}")
    if data.size_bytes > max_bytes:
        raise bad_request("file_too_large", f"Maximum size is {max_bytes // (1024 * 1024)} MB")
    pending = await db.scalar(
        select(func.count())
        .select_from(Media)
        .where(Media.owner_id == user.id, Media.state == MediaState.uploading)
    )
    if (pending or 0) >= MAX_PENDING_UPLOADS:
        raise AppError(429, "too_many_pending_uploads", "Finish your current uploads first")

    media = Media(
        id=uuid7(),
        owner_id=user.id,
        purpose=data.purpose,
        kind=data.kind,
        mime=data.mime,
        size_bytes=data.size_bytes,
        state=MediaState.uploading,
    )
    db.add(media)
    await db.commit()
    url = await storage.presign_put(raw_key(media), data.mime, data.size_bytes)
    return UploadUrlOut(
        media_id=media.id,
        upload_url=url,
        headers={"Content-Type": data.mime},
        expires_in=settings.upload_url_ttl_seconds,
    )


async def complete_upload(db: AsyncSession, user: User, media_id: uuid.UUID) -> Media:
    media = await db.get(Media, media_id)
    if media is None or media.owner_id != user.id:
        raise not_found("Media")
    if media.state != MediaState.uploading:
        return media  # idempotent
    head = await storage.head(settings.s3_bucket_raw, raw_key(media))
    if head is None:
        raise bad_request("upload_missing", "The file has not been uploaded yet")
    media.state = MediaState.processing
    await db.commit()
    from tasks import enqueue

    await enqueue("process_media", str(media.id), job_id=f"process_media:{media.id}")
    if not settings.tasks_eager:
        return media
    await db.refresh(media)
    return media


async def get_owned_media(db: AsyncSession, user: User, media_id: uuid.UUID) -> Media:
    media = await db.get(Media, media_id)
    if media is None or media.owner_id != user.id or media.state == MediaState.deleted:
        raise not_found("Media")
    return media


# --- Worker side -------------------------------------------------------------------------------


async def _process_file(media: Media, src: Path, workdir: Path) -> ProcessedMedia:
    if media.kind == MediaKind.image:
        return process_image(src, media.purpose, workdir)
    return await process_video(src, workdir)


async def process_media(media_id: uuid.UUID, *, final_attempt: bool) -> None:
    """Idempotent. Raises ModerationUnavailableError for the caller to retry with backoff."""
    async with SessionLocal() as db:
        media = await db.get(Media, media_id)
        if media is None or media.state != MediaState.processing:
            return
        _, max_bytes = limits_for(media.kind)
        key = raw_key(media)
        reject_reason: str | None = None
        verdict: moderation.Verdict | None = None
        processed: ProcessedMedia | None = None
        with new_workdir() as tmp:
            workdir = Path(tmp)
            try:
                head = await storage.head(settings.s3_bucket_raw, key)
                if head is None:
                    raise MediaRejectedError("Upload not found")
                if int(head.get("ContentLength", 0)) > max_bytes:
                    raise MediaRejectedError("File is too large")
                src = workdir / "source"
                try:
                    await storage.download(settings.s3_bucket_raw, key, src, max_bytes)
                except ValueError as exc:
                    raise MediaRejectedError("File is too large") from exc
                processed = await _process_file(media, src, workdir)
                try:
                    verdict = await moderation.moderate_images(processed.moderation_frames)
                except moderation.ModerationUnavailableError:
                    if not final_attempt:
                        raise
                    verdict = moderation.Verdict("review", reasons=["moderation_unavailable"])
                if verdict.action == "reject":
                    raise MediaRejectedError("This media violates the content rules")
                media.variants = await upload_variants(media.id, processed)
                media.width, media.height = processed.width, processed.height
                media.duration_seconds = processed.duration
                media.moderation = verdict.as_json()
                media.state = MediaState.ready
            except MediaRejectedError as exc:
                reject_reason = str(exc)
                media.state = MediaState.rejected
                media.reject_reason = reject_reason
                if verdict is not None:
                    media.moderation = verdict.as_json()
        await db.commit()
        try:
            await storage.delete_keys(settings.s3_bucket_raw, [key])
        except Exception:
            logger.warning("could not delete raw upload %s", key, exc_info=True)
        if media.post_id is not None:
            import posts_service

            await posts_service.on_media_settled(media.post_id)
        logger.info("media %s -> %s (%s)", media.id, media.state, reject_reason or "ok")


async def import_remote_avatar(user_id: str, picture_url: str) -> None:
    """Copy a Google profile picture into our storage so we never hotlink third parties."""
    from urllib.parse import urlsplit

    host = urlsplit(picture_url).hostname or ""
    if not host.endswith(".googleusercontent.com"):
        logger.info("skipping avatar import from untrusted host %s", host)
        return
    try:
        fetched = await safe_get(picture_url, max_bytes=5 * 1024 * 1024, accept="image/*")
    except (BlockedURLError, OSError, TimeoutError) as exc:
        logger.info("avatar import failed: %r", exc)
        return
    if fetched.status != 200 or not fetched.content_type.startswith("image/"):
        return
    async with SessionLocal() as db:
        user = await db.get(User, uuid.UUID(user_id))
        if user is None or user.avatar:
            return
        media = Media(
            id=uuid7(),
            owner_id=user.id,
            purpose=MediaPurpose.avatar,
            kind=MediaKind.image,
            mime=fetched.content_type,
            size_bytes=len(fetched.body),
            state=MediaState.processing,
        )
        with new_workdir() as tmp:
            src = Path(tmp) / "source"
            src.write_bytes(fetched.body)
            try:
                processed = process_image(src, MediaPurpose.avatar, Path(tmp))
            except MediaRejectedError:
                return
            media.variants = await upload_variants(media.id, processed)
        media.state = MediaState.ready
        db.add(media)
        user.avatar = dict(media.variants)
        await db.commit()


async def delete_post_media(post_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        rows = (
            await db.scalars(
                select(Media).where(Media.post_id == post_id, Media.state != MediaState.deleted)
            )
        ).all()
        keys = [k for m in rows for k in m.variants.values()]
        await storage.delete_keys(settings.s3_bucket_public, keys)
        await db.execute(
            update(Media)
            .where(Media.post_id == post_id)
            .values(state=MediaState.deleted, variants={})
        )
        await db.commit()


async def cleanup_stale_uploads() -> int:
    """Remove uploads that were never completed (or got stuck) after a day."""
    cutoff = utcnow() - timedelta(days=1)
    async with SessionLocal() as db:
        rows = (
            await db.scalars(
                select(Media)
                .where(
                    Media.state.in_([MediaState.uploading, MediaState.processing]),
                    Media.created_at < cutoff,
                )
                .limit(500)
            )
        ).all()
        if not rows:
            return 0
        await storage.delete_keys(settings.s3_bucket_raw, [raw_key(m) for m in rows])
        await db.execute(
            update(Media).where(Media.id.in_([m.id for m in rows])).values(state=MediaState.deleted)
        )
        await db.commit()
        return len(rows)
