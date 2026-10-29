"""Feeds (following / latest / category / tag / solved / trending / user), search and trending.

Every list is keyset-paginated on (time, id) and served by a partial index. Viewer filters
(blocks, mutes, muted words/categories, content warnings) are applied in SQL.
"""

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import Select, and_, func, literal, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from cache import cache_delete, cache_get_json, cache_set_json, get_redis
from database import SessionLocal
from models import Category, Follow, ModerationState, Post, PostStatus, Tag, TopicFollow, User
from posts_service import hydrate, post_load_options
from schemas import PostPage, SearchOut, TagOut
from social_service import ViewerContext, load_viewer_ctx
from users_service import get_visible_user, user_summary
from utils import (
    decode_cursor,
    decode_offset_cursor,
    encode_cursor,
    encode_offset_cursor,
    escape_like,
    keyset_before,
)

logger = logging.getLogger(__name__)

PAGE = 20
TRENDING_WINDOW_DAYS = 7
TRENDING_SIZE = 500
TRENDING_PER_CATEGORY = 200
FOLLOWING_CACHE_TTL = 30
MAX_SEARCH_OFFSET = 100
SEARCH_CANDIDATES = 500


def _live() -> list[Any]:
    return [
        Post.moderation_state == ModerationState.published,
        Post.deleted_at.is_(None),
        Post.author_hidden.is_(False),
    ]


def _viewer_filters(ctx: ViewerContext) -> list[Any]:
    filters: list[Any] = []
    if ctx.hidden_author_ids:
        filters.append(Post.author_id.not_in(ctx.hidden_author_ids))
    if ctx.content.muted_categories:
        filters.append(Post.category.not_in(ctx.content.muted_categories))
    if ctx.content.hide_content_warning_posts:
        filters.append(Post.content_warning.is_(False))
    if ctx.content.muted_words:
        patterns = [f"%{escape_like(w)}%" for w in ctx.content.muted_words]
        filters.append(
            not_(
                or_(
                    *(
                        or_(Post.title.ilike(p, escape="\\"), Post.body.ilike(p, escape="\\"))
                        for p in patterns
                    )
                )
            )
        )
    return filters


async def _page(
    db: AsyncSession,
    query: Select[Any],
    viewer: User | None,
    cursor: str | None,
    time_col: Any = Post.created_at,
) -> PostPage:
    position = decode_cursor(cursor)
    if position:
        query = query.where(keyset_before(time_col, Post.id, position))
    posts = list(
        (
            await db.scalars(
                query.options(*post_load_options())
                .order_by(time_col.desc(), Post.id.desc())
                .limit(PAGE + 1)
            )
        ).all()
    )
    has_more = len(posts) > PAGE
    posts = posts[:PAGE]
    next_cursor = None
    if has_more and posts:
        last = posts[-1]
        stamp = last.solved_at if time_col is Post.solved_at else last.created_at
        assert stamp is not None
        next_cursor = encode_cursor(stamp, last.id)
    return PostPage(items=await hydrate(db, posts, viewer), next_cursor=next_cursor)


# --- Feeds -------------------------------------------------------------------------------------


def _following_key(user_id: uuid.UUID) -> str:
    return f"feed_following:{user_id}"


async def invalidate_following_cache(user_id: uuid.UUID) -> None:
    await cache_delete(_following_key(user_id))


async def following(db: AsyncSession, viewer: User, cursor: str | None) -> PostPage:
    """Posts from people I follow (never their anonymous ones), followed topics, and my own."""
    ctx = await load_viewer_ctx(db, viewer)
    if cursor is None:
        cached = await cache_get_json(_following_key(viewer.id))
        if cached is not None:
            return await _from_id_snapshot(db, viewer, cached["ids"], cached["next"])
    topics = (
        await db.scalars(select(TopicFollow.topic).where(TopicFollow.user_id == viewer.id))
    ).all()
    categories = [t.split(":", 1)[1] for t in topics if t.startswith("category:")]
    tags = [t.split(":", 1)[1] for t in topics if t.startswith("tag:")]
    followed = select(Follow.followee_id).where(Follow.follower_id == viewer.id)
    sources = [
        and_(Post.author_id.in_(followed), Post.is_anonymous.is_(False)),
        Post.author_id == viewer.id,
    ]
    if categories:
        sources.append(Post.category.in_([c for c in categories if c in Category.__members__]))
    if tags:
        sources.append(Post.tags.overlap(tags))
    query = select(Post).where(*_live(), or_(*sources), *_viewer_filters(ctx))
    page = await _page(db, query, viewer, cursor)
    if cursor is None:
        await cache_set_json(
            _following_key(viewer.id),
            {"ids": [str(p.id) for p in page.items], "next": page.next_cursor},
            FOLLOWING_CACHE_TTL,
        )
    return page


async def _from_id_snapshot(
    db: AsyncSession, viewer: User | None, ids: list[str], next_cursor: str | None
) -> PostPage:
    """Hydrate cached ids, preserving order and dropping posts that became unavailable."""
    if not ids:
        return PostPage(items=[], next_cursor=next_cursor)
    ctx = await load_viewer_ctx(db, viewer)
    uuids = [uuid.UUID(i) for i in ids]
    posts = (
        await db.scalars(
            select(Post)
            .options(*post_load_options())
            .where(Post.id.in_(uuids), *_live(), *_viewer_filters(ctx))
        )
    ).all()
    by_id = {p.id: p for p in posts}
    ordered = [by_id[i] for i in uuids if i in by_id]
    return PostPage(items=await hydrate(db, ordered, viewer), next_cursor=next_cursor)


async def latest(
    db: AsyncSession,
    viewer: User | None,
    cursor: str | None,
    category: Category | None = None,
    tag: str | None = None,
) -> PostPage:
    ctx = await load_viewer_ctx(db, viewer)
    query = select(Post).where(*_live(), *_viewer_filters(ctx))
    if category is not None:
        query = query.where(Post.category == category)
    if tag is not None:
        query = query.where(Post.tags.contains([tag]))
    return await _page(db, query, viewer, cursor)


async def solved(db: AsyncSession, viewer: User | None, cursor: str | None) -> PostPage:
    ctx = await load_viewer_ctx(db, viewer)
    query = select(Post).where(
        *_live(),
        Post.status == PostStatus.solved,
        Post.solved_at.is_not(None),
        *_viewer_filters(ctx),
    )
    return await _page(db, query, viewer, cursor, time_col=Post.solved_at)


async def user_posts(
    db: AsyncSession, handle: str, viewer: User | None, cursor: str | None
) -> PostPage:
    owner = await get_visible_user(db, handle, viewer)
    query = select(Post).where(Post.author_id == owner.id, Post.deleted_at.is_(None))
    if viewer is None or viewer.id != owner.id:
        # Other people only ever see the public, published rants.
        query = query.where(
            Post.is_anonymous.is_(False), Post.moderation_state == ModerationState.published
        )
    return await _page(db, query, viewer, cursor)


# --- Trending ----------------------------------------------------------------------------------


def _trending_key(category: Category | None) -> str:
    return f"trending:{category.value if category else 'all'}"


# Reddit-style hot score: log-scaled engagement plus a recency term (1 point per 12.5 hours).
HOT_SCORE = (
    func.log(
        func.greatest(
            Post.same_count
            + Post.hug_count
            + Post.rage_count
            + Post.lol_count
            + 2 * Post.comment_count,
            1,
        )
    )
    + func.extract("epoch", Post.created_at) / 45000
)


async def compute_trending() -> int:
    """Cron: rank recent posts by hot score into Redis sorted sets, swapped in atomically."""
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(Post.id, Post.category, HOT_SCORE.label("score"))
                .where(
                    *_live(), Post.created_at > func.now() - timedelta(days=TRENDING_WINDOW_DAYS)
                )
                .order_by(HOT_SCORE.desc())
                .limit(TRENDING_SIZE * 2)
            )
        ).all()
    redis = get_redis()
    buckets: dict[str, dict[str, float]] = {"all": {}}
    for post_id, category, score in rows:
        if len(buckets["all"]) < TRENDING_SIZE:
            buckets["all"][str(post_id)] = float(score)
        cat = buckets.setdefault(category.value, {})
        if len(cat) < TRENDING_PER_CATEGORY:
            cat[str(post_id)] = float(score)
    async with redis.pipeline(transaction=True) as pipe:
        for name in ["all", *[c.value for c in Category]]:
            key = f"trending:{name}"
            members = buckets.get(name)
            if members:
                pipe.delete(f"{key}:tmp")
                pipe.zadd(f"{key}:tmp", members)
                pipe.rename(f"{key}:tmp", key)
            else:
                pipe.delete(key)
        pipe.set("trending:computed", "1", ex=900)
        await pipe.execute()
    return len(rows)


async def trending(
    db: AsyncSession, viewer: User | None, cursor: str | None, category: Category | None = None
) -> PostPage:
    redis = get_redis()
    if not await redis.exists("trending:computed"):
        await compute_trending()
    offset = decode_offset_cursor(cursor, TRENDING_SIZE)
    ids = await redis.zrevrange(_trending_key(category), offset, offset + PAGE - 1)
    total = await redis.zcard(_trending_key(category))
    next_offset = offset + PAGE
    next_cursor = encode_offset_cursor(next_offset) if next_offset < total else None
    decoded = [i.decode() if isinstance(i, bytes) else i for i in ids]
    return await _from_id_snapshot(db, viewer, decoded, next_cursor)


# --- Search ------------------------------------------------------------------------------------


async def search(
    db: AsyncSession, viewer: User | None, q: str, kind: str, cursor: str | None
) -> SearchOut:
    q = " ".join(q.split())[:100]
    offset = decode_offset_cursor(cursor, MAX_SEARCH_OFFSET)
    ctx = await load_viewer_ctx(db, viewer)
    out = SearchOut(posts=[], users=[], tags=[], next_cursor=None)
    if kind in ("all", "posts"):
        tsquery = func.websearch_to_tsquery("english", q)
        # Rank only the most recent matches: bounded cost even when a term matches everything.
        candidates = (
            select(Post.id, Post.search_tsv)
            .where(*_live(), Post.search_tsv.op("@@")(tsquery), *_viewer_filters(ctx))
            .order_by(Post.created_at.desc())
            .limit(SEARCH_CANDIDATES)
            .subquery()
        )
        posts = list(
            (
                await db.scalars(
                    select(Post)
                    .options(*post_load_options())
                    .join(candidates, candidates.c.id == Post.id)
                    .order_by(
                        func.ts_rank_cd(candidates.c.search_tsv, tsquery).desc(),
                        Post.created_at.desc(),
                    )
                    .offset(offset)
                    .limit(PAGE + 1)
                )
            ).all()
        )
        if len(posts) > PAGE and offset + PAGE <= MAX_SEARCH_OFFSET:
            out.next_cursor = encode_offset_cursor(offset + PAGE)
        out.posts = await hydrate(db, posts[:PAGE], viewer)
    if kind in ("all", "users") and offset == 0:
        from models import UserSettings, UserStatus

        pattern = f"%{escape_like(q.lower().lstrip('@'))}%"
        query = (
            select(User)
            .outerjoin(UserSettings, UserSettings.user_id == User.id)
            .where(
                User.status.in_([UserStatus.active, UserStatus.suspended]),
                User.onboarded.is_(True),
                or_(
                    User.handle.ilike(pattern, escape="\\"),
                    User.display_name.ilike(pattern, escape="\\"),
                ),
                func.coalesce(UserSettings.privacy["searchable"].as_boolean(), literal(True)),
            )
            .order_by(
                func.greatest(
                    func.similarity(User.handle, q), func.similarity(User.display_name, q)
                ).desc()
            )
            .limit(10)
        )
        if ctx.blocked_ids:
            query = query.where(User.id.not_in(ctx.blocked_ids))
        out.users = [user_summary(u) for u in (await db.scalars(query)).all()]
    if kind in ("all", "tags") and offset == 0:
        words = [w.lower().lstrip("#") for w in q.split()[:3] if len(w.lstrip("#")) >= 2]
        if words:
            tags = (
                await db.scalars(
                    select(Tag)
                    .where(
                        or_(*(Tag.name.like(escape_like(w) + "%", escape="\\") for w in words)),
                        Tag.post_count > 0,
                    )
                    .order_by(Tag.post_count.desc())
                    .limit(10)
                )
            ).all()
            out.tags = [TagOut.model_validate(t) for t in tags]
    return out
