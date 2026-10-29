"""arq worker: background jobs and cron tasks. Run with `arq worker.WorkerSettings`.

Every job is idempotent, so arq retries (with exponential backoff) are always safe.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from arq import Retry
from arq.cron import cron
from sqlalchemy import select

import comments_service
import feed
import link_preview
import mailer
import media_service
import moderation
import posts_service
import users_service
from cache import close_redis, init_redis, redis_settings
from database import SessionLocal
from http_client import close_http_client
from models import Comment, ModerationState, Post
from storage import close_s3
from utils import utcnow

logger = logging.getLogger(__name__)

MAX_TRIES = 6


def _backoff(ctx: dict[str, Any]) -> int:
    return min(600, 10 * 2 ** (ctx.get("job_try", 1) - 1))


def _final(ctx: dict[str, Any]) -> bool:
    return bool(ctx.get("eager")) or ctx.get("job_try", 1) >= MAX_TRIES


async def send_email(ctx: dict[str, Any], kind: str, to: str, name: str, token: str) -> None:
    builders = {
        "verification": lambda: mailer.verification_email(to, name, token),
        "password_reset": lambda: mailer.password_reset_email(to, name, token),
        "account_deletion": lambda: mailer.account_deletion_email(to, name),
    }
    try:
        await mailer.deliver(builders[kind]())
    except Exception as exc:
        if _final(ctx):
            logger.exception("giving up sending %s email", kind)
            return
        raise Retry(defer=_backoff(ctx)) from exc


async def process_media(ctx: dict[str, Any], media_id: str) -> None:
    try:
        await media_service.process_media(uuid.UUID(media_id), final_attempt=_final(ctx))
    except moderation.ModerationUnavailableError as exc:
        raise Retry(defer=_backoff(ctx)) from exc


async def moderate_post(ctx: dict[str, Any], post_id: str) -> None:
    if not await posts_service.remoderate_post(uuid.UUID(post_id)) and not ctx.get("eager"):
        raise Retry(defer=_backoff(ctx))


async def moderate_comment(ctx: dict[str, Any], comment_id: str) -> None:
    if not await comments_service.remoderate_comment(uuid.UUID(comment_id)) and not ctx.get(
        "eager"
    ):
        raise Retry(defer=_backoff(ctx))


async def fetch_link_preview(ctx: dict[str, Any], post_id: str) -> None:
    await link_preview.fetch_for_post(uuid.UUID(post_id))


async def import_avatar(ctx: dict[str, Any], user_id: str, picture_url: str) -> None:
    await media_service.import_remote_avatar(user_id, picture_url)


async def delete_post_media(ctx: dict[str, Any], post_id: str) -> None:
    await media_service.delete_post_media(uuid.UUID(post_id))


# --- Cron --------------------------------------------------------------------------------------


async def cron_trending(ctx: dict[str, Any]) -> None:
    count = await feed.compute_trending()
    logger.info("trending recomputed from %d posts", count)


async def cron_cleanup_uploads(ctx: dict[str, Any]) -> None:
    removed = await media_service.cleanup_stale_uploads()
    if removed:
        logger.info("cleaned %d stale uploads", removed)


async def cron_purge_accounts(ctx: dict[str, Any]) -> None:
    purged = await users_service.purge_due_accounts()
    if purged:
        logger.info("purged %d deleted accounts", purged)


async def cron_sweep_pending_moderation(ctx: dict[str, Any]) -> None:
    """Safety net: anything still `pending` (e.g. a lost job) gets moderated again."""
    cutoff = utcnow() - timedelta(minutes=2)
    async with SessionLocal() as db:
        posts = (
            await db.scalars(
                select(Post.id)
                .where(Post.moderation_state == ModerationState.pending, Post.updated_at < cutoff)
                .limit(200)
            )
        ).all()
        comments = (
            await db.scalars(
                select(Comment.id)
                .where(
                    Comment.moderation_state == ModerationState.pending, Comment.updated_at < cutoff
                )
                .limit(200)
            )
        ).all()
    for post_id in posts:
        await posts_service.remoderate_post(post_id)
    for comment_id in comments:
        await comments_service.remoderate_comment(comment_id)


JOBS: dict[str, Any] = {
    "send_email": send_email,
    "process_media": process_media,
    "moderate_post": moderate_post,
    "moderate_comment": moderate_comment,
    "fetch_link_preview": fetch_link_preview,
    "import_avatar": import_avatar,
    "delete_post_media": delete_post_media,
}


async def startup(ctx: dict[str, Any]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await init_redis()


async def shutdown(ctx: dict[str, Any]) -> None:
    await close_http_client()
    await close_s3()
    await close_redis()


class WorkerSettings:
    functions = list(JOBS.values())
    cron_jobs = [
        cron(cron_trending, minute=set(range(0, 60, 5)), run_at_startup=True, unique=True),
        cron(cron_sweep_pending_moderation, minute=set(range(1, 60, 10)), unique=True),
        cron(cron_cleanup_uploads, minute={17}, unique=True),
        cron(cron_purge_accounts, hour={3}, minute={30}, unique=True),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_tries = MAX_TRIES
    max_jobs = 8
    job_timeout = 900
    keep_result = 60
