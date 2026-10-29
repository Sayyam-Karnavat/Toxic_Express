"""Social graph: follows, blocks, mutes, topic follows, and the cached per-viewer context used to
filter feeds and comments."""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cache import cache_delete, cache_get_json, cache_set_json
from errors import bad_request
from models import Block, Follow, Mute, TopicFollow, User
from notifications_service import notify
from schemas import ContentSettings, UserPage, UserSummary
from users_service import get_visible_user, load_settings, user_summary
from utils import decode_cursor, encode_cursor, keyset_before

VIEWER_CTX_TTL = 300


@dataclass
class ViewerContext:
    user_id: uuid.UUID | None = None
    blocked_ids: set[uuid.UUID] = field(default_factory=set)  # blocked by me or blocking me
    muted_ids: set[uuid.UUID] = field(default_factory=set)
    content: ContentSettings = field(default_factory=ContentSettings)

    @property
    def hidden_author_ids(self) -> set[uuid.UUID]:
        return self.blocked_ids | self.muted_ids


def _ctx_key(user_id: uuid.UUID) -> str:
    return f"viewer_ctx:{user_id}"


async def load_viewer_ctx(db: AsyncSession, viewer: User | None) -> ViewerContext:
    if viewer is None:
        return ViewerContext()
    cached = await cache_get_json(_ctx_key(viewer.id))
    if cached is not None:
        return ViewerContext(
            user_id=viewer.id,
            blocked_ids={uuid.UUID(x) for x in cached["blocked"]},
            muted_ids={uuid.UUID(x) for x in cached["muted"]},
            content=ContentSettings.model_validate(cached["content"]),
        )
    blocked = set(
        (await db.scalars(select(Block.blocked_id).where(Block.blocker_id == viewer.id))).all()
    )
    blocked |= set(
        (await db.scalars(select(Block.blocker_id).where(Block.blocked_id == viewer.id))).all()
    )
    muted = set((await db.scalars(select(Mute.muted_id).where(Mute.muter_id == viewer.id))).all())
    content = (await load_settings(db, viewer.id)).content
    await cache_set_json(
        _ctx_key(viewer.id),
        {
            "blocked": [str(x) for x in blocked],
            "muted": [str(x) for x in muted],
            "content": content.model_dump(mode="json"),
        },
        VIEWER_CTX_TTL,
    )
    return ViewerContext(user_id=viewer.id, blocked_ids=blocked, muted_ids=muted, content=content)


async def invalidate_viewer_ctx(*user_ids: uuid.UUID) -> None:
    await cache_delete(*(_ctx_key(u) for u in user_ids))


async def _target(db: AsyncSession, user: User, handle: str) -> User:
    target = await get_visible_user(db, handle, user)
    if target.id == user.id:
        raise bad_request("invalid_target", "You can't do that to yourself")
    return target


async def _adjust_follow_counts(
    db: AsyncSession, follower: uuid.UUID, followee: uuid.UUID, delta: int
) -> None:
    await db.execute(
        update(User).where(User.id == follower).values(following_count=User.following_count + delta)
    )
    await db.execute(
        update(User).where(User.id == followee).values(follower_count=User.follower_count + delta)
    )


async def follow(db: AsyncSession, user: User, handle: str) -> None:
    target = await _target(db, user, handle)
    ctx = await load_viewer_ctx(db, user)
    if target.id in ctx.blocked_ids:
        raise bad_request("blocked", "You can't follow this user")
    inserted = await db.scalar(
        insert(Follow)
        .values(follower_id=user.id, followee_id=target.id)
        .on_conflict_do_nothing()
        .returning(Follow.followee_id)
    )
    if inserted:
        await _adjust_follow_counts(db, user.id, target.id, 1)
        await notify(
            db, user_id=target.id, type="follow", actor_id=user.id, dedupe_key=f"follow:{user.id}"
        )
    await db.commit()


async def _remove_follow(db: AsyncSession, follower: uuid.UUID, followee: uuid.UUID) -> None:
    removed = await db.scalar(
        delete(Follow)
        .where(Follow.follower_id == follower, Follow.followee_id == followee)
        .returning(Follow.followee_id)
    )
    if removed:
        await _adjust_follow_counts(db, follower, followee, -1)


async def unfollow(db: AsyncSession, user: User, handle: str) -> None:
    target = await get_visible_user(db, handle, user)
    await _remove_follow(db, user.id, target.id)
    await db.commit()


async def block(db: AsyncSession, user: User, handle: str) -> None:
    target = await _target(db, user, handle)
    await db.execute(
        insert(Block).values(blocker_id=user.id, blocked_id=target.id).on_conflict_do_nothing()
    )
    await _remove_follow(db, user.id, target.id)
    await _remove_follow(db, target.id, user.id)
    await db.commit()
    await invalidate_viewer_ctx(user.id, target.id)


async def unblock(db: AsyncSession, user: User, user_id: uuid.UUID) -> None:
    await db.execute(delete(Block).where(Block.blocker_id == user.id, Block.blocked_id == user_id))
    await db.commit()
    await invalidate_viewer_ctx(user.id, user_id)


async def mute(db: AsyncSession, user: User, handle: str) -> None:
    target = await _target(db, user, handle)
    await db.execute(
        insert(Mute).values(muter_id=user.id, muted_id=target.id).on_conflict_do_nothing()
    )
    await db.commit()
    await invalidate_viewer_ctx(user.id)


async def unmute(db: AsyncSession, user: User, user_id: uuid.UUID) -> None:
    await db.execute(delete(Mute).where(Mute.muter_id == user.id, Mute.muted_id == user_id))
    await db.commit()
    await invalidate_viewer_ctx(user.id)


async def _user_page(db: AsyncSession, query: Any, limit: int) -> UserPage:
    """`query` selects (User, created_at) ordered newest first."""
    rows: list[tuple[User, Any]] = [
        tuple(r) for r in (await db.execute(query.limit(limit + 1))).all()
    ]
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = [user_summary(user) for user, _ in rows]
    next_cursor = encode_cursor(rows[-1][1], rows[-1][0].id) if has_more and rows else None
    return UserPage(items=items, next_cursor=next_cursor)


async def list_follows(
    db: AsyncSession,
    handle: str,
    viewer: User | None,
    direction: str,
    cursor: str | None,
    limit: int = 20,
) -> UserPage:
    owner = await get_visible_user(db, handle, viewer)
    if direction == "followers":
        join_on, where = Follow.follower_id == User.id, Follow.followee_id == owner.id
    else:
        join_on, where = Follow.followee_id == User.id, Follow.follower_id == owner.id
    query = (
        select(User, Follow.created_at)
        .join(Follow, join_on)
        .where(where, User.status.in_(["active", "suspended"]))
        .order_by(Follow.created_at.desc(), User.id.desc())
    )
    position = decode_cursor(cursor)
    if position:
        query = query.where(keyset_before(Follow.created_at, User.id, position))
    return await _user_page(db, query, limit)


async def list_blocked_or_muted(db: AsyncSession, user: User, kind: str) -> list[UserSummary]:
    if kind == "blocks":
        query = (
            select(User)
            .join(Block, Block.blocked_id == User.id)
            .where(Block.blocker_id == user.id)
            .order_by(Block.created_at.desc())
        )
    else:
        query = (
            select(User)
            .join(Mute, Mute.muted_id == User.id)
            .where(Mute.muter_id == user.id)
            .order_by(Mute.created_at.desc())
        )
    return [user_summary(u) for u in (await db.scalars(query.limit(500))).all()]


async def follow_topic(db: AsyncSession, user: User, topic: str) -> None:
    count = len(
        (await db.scalars(select(TopicFollow.topic).where(TopicFollow.user_id == user.id))).all()
    )
    if count >= 50:
        raise bad_request("too_many_topics", "You can follow up to 50 topics")
    await db.execute(
        insert(TopicFollow).values(user_id=user.id, topic=topic).on_conflict_do_nothing()
    )
    await db.commit()


async def unfollow_topic(db: AsyncSession, user: User, topic: str) -> None:
    await db.execute(
        delete(TopicFollow).where(TopicFollow.user_id == user.id, TopicFollow.topic == topic)
    )
    await db.commit()


async def list_topics(db: AsyncSession, user: User) -> list[str]:
    return list(
        (
            await db.scalars(
                select(TopicFollow.topic)
                .where(TopicFollow.user_id == user.id)
                .order_by(TopicFollow.created_at)
            )
        ).all()
    )
