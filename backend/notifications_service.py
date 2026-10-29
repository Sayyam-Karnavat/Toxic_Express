"""In-app notifications: deduplicated, preference-aware, never leaking anonymous authors."""

import uuid
from typing import Any

from sqlalchemy import exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cache import cache_delete, cache_get_json, cache_set_json
from models import Block, Notification, UserSettings
from schemas import NotificationOut, NotificationPage
from users_service import user_summary
from utils import decode_cursor, encode_cursor, keyset_before, utcnow

# notification type -> NotificationSettings flag (None = always delivered)
PREFERENCE_FOR = {
    "reaction": "reactions",
    "comment": "comments",
    "reply": "replies",
    "follow": "follows",
    "solved": "solved",
    "helpful": "helpful",
    "badge": None,
    "moderation": None,
    "media_rejected": None,
    "appeal": None,
}
UNREAD_TTL = 15


def _unread_key(user_id: uuid.UUID) -> str:
    return f"notif_unread:{user_id}"


async def notify(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    type: str,
    actor_id: uuid.UUID | None = None,
    post_id: uuid.UUID | None = None,
    comment_id: uuid.UUID | None = None,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Queue a notification inside the caller's transaction.

    Pass actor_id=None to hide the actor (e.g. anonymous authors). Self-notifications and
    notifications from users the recipient blocked are dropped.
    """
    if actor_id is not None and actor_id == user_id:
        return
    pref = PREFERENCE_FOR.get(type)
    if pref is not None:
        prefs = await db.scalar(
            select(UserSettings.notifications).where(UserSettings.user_id == user_id)
        )
        if prefs and prefs.get(pref) is False:
            return
    if actor_id is not None and await db.scalar(
        select(exists().where(Block.blocker_id == user_id, Block.blocked_id == actor_id))
    ):
        return
    key = dedupe_key or f"{type}:{uuid.uuid4()}"
    stmt = insert(Notification).values(
        user_id=user_id,
        type=type,
        actor_id=actor_id,
        post_id=post_id,
        comment_id=comment_id,
        data=data or {},
        dedupe_key=key[:160],
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_notifications_user_dedupe",
        set_={
            "created_at": func.now(),
            "read_at": None,
            "actor_id": stmt.excluded.actor_id,
            "data": stmt.excluded.data,
        },
    )
    await db.execute(stmt)
    await cache_delete(_unread_key(user_id))


async def list_notifications(
    db: AsyncSession, user_id: uuid.UUID, cursor: str | None, limit: int = 20
) -> NotificationPage:
    query = (
        select(Notification)
        .options(selectinload(Notification.actor))
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit + 1)
    )
    position = decode_cursor(cursor)
    if position:
        query = query.where(keyset_before(Notification.created_at, Notification.id, position))
    rows = list((await db.scalars(query)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [
        NotificationOut(
            id=n.id,
            type=n.type,
            actor=user_summary(n.actor) if n.actor is not None else None,
            post_id=n.post_id,
            comment_id=n.comment_id,
            data=n.data,
            read=n.read_at is not None,
            created_at=n.created_at,
        )
        for n in rows
    ]
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return NotificationPage(items=items, next_cursor=next_cursor)


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    cached = await cache_get_json(_unread_key(user_id))
    if cached is not None:
        return int(cached)
    count = (
        await db.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
        or 0
    )
    await cache_set_json(_unread_key(user_id), count, UNREAD_TTL)
    return count


async def mark_read(db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID], all_: bool) -> None:
    query = update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if not all_:
        if not ids:
            return
        query = query.where(Notification.id.in_(ids))
    await db.execute(query.values(read_at=utcnow()))
    await db.commit()
    await cache_delete(_unread_key(user_id))
