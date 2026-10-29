"""Rants: create/edit/delete with moderation, reactions, solving, and response hydration."""

import logging
import re
import uuid
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import moderation
from database import SessionLocal
from errors import AppError, bad_request, forbidden, not_found
from media_service import media_out
from models import (
    Comment,
    Media,
    MediaKind,
    MediaPurpose,
    MediaState,
    ModerationState,
    Post,
    PostStatus,
    Reaction,
    ReactionKind,
    Tag,
    User,
)
from notifications_service import notify
from reputation import PINNED_ANSWER_POINTS, add_helper_score, check_badges
from schemas import AnonPostOut, AnyPostOut, PostCreateIn, PostOut, PostUpdateIn, ReactionCounts
from social_service import load_viewer_ctx
from tasks import enqueue
from users_service import load_settings, user_summary
from utils import utcnow, uuid7

logger = logging.getLogger(__name__)

EDIT_WINDOW = timedelta(minutes=15)
REACTION_COLUMN = {
    ReactionKind.same: Post.same_count,
    ReactionKind.hug: Post.hug_count,
    ReactionKind.rage: Post.rage_count,
    ReactionKind.lol: Post.lol_count,
}
_URL = re.compile(r"https?://[^\s<>()\"']+", re.IGNORECASE)
LIVE_STATES = (ModerationState.published,)


def post_load_options() -> list:
    return [selectinload(Post.author), selectinload(Post.media)]


# --- Hydration ---------------------------------------------------------------------------------


async def hydrate(db: AsyncSession, posts: Sequence[Post], viewer: User | None) -> list[AnyPostOut]:
    """Posts must be loaded with post_load_options(). One extra query for the viewer's reactions."""
    if not posts:
        return []
    mine: dict[uuid.UUID, ReactionKind] = {}
    if viewer is not None:
        rows = await db.execute(
            select(Reaction.post_id, Reaction.kind).where(
                Reaction.user_id == viewer.id, Reaction.post_id.in_([p.id for p in posts])
            )
        )
        mine = {post_id: kind for post_id, kind in rows.all()}
    now = utcnow()
    out: list[AnyPostOut] = []
    for p in posts:
        is_own = viewer is not None and viewer.id == p.author_id
        common = {
            "id": p.id,
            "title": p.title,
            "body": p.body,
            "category": p.category,
            "tags": p.tags,
            "frustration_level": p.frustration_level,
            "status": p.status,
            "moderation_state": p.moderation_state,
            "content_warning": p.content_warning,
            "show_crisis_resources": p.crisis_flag,
            "media": [media_out(m) for m in p.media if m.state == MediaState.ready or is_own],
            "reactions": ReactionCounts(
                same=p.same_count,
                hug=p.hug_count,
                rage=p.rage_count,
                lol=p.lol_count,
                total=p.same_count + p.hug_count + p.rage_count + p.lol_count,
            ),
            "my_reaction": mine.get(p.id),
            "comment_count": p.comment_count,
            "pinned_comment_id": p.pinned_comment_id,
            "solved_at": p.solved_at,
            "link_preview": p.link_preview,
            "created_at": p.created_at,
            "edited_at": p.edited_at,
            "is_own": is_own,
            "can_edit": is_own
            and now - p.created_at < EDIT_WINDOW
            and p.moderation_state not in (ModerationState.removed, ModerationState.rejected),
        }
        if p.is_anonymous:
            out.append(AnonPostOut(**common))
        else:
            out.append(PostOut(**common, author=user_summary(p.author)))
    return out


# --- Lookup & visibility -----------------------------------------------------------------------


async def load_post(db: AsyncSession, post_id: uuid.UUID, *, for_update: bool = False) -> Post:
    query = select(Post).where(Post.id == post_id, Post.deleted_at.is_(None))
    query = query.with_for_update() if for_update else query.options(*post_load_options())
    # Counters change through SQL UPDATEs; always refresh identity-mapped rows.
    query = query.execution_options(populate_existing=True)
    post = await db.scalar(query)
    if post is None:
        raise not_found("Post")
    return post


async def ensure_visible(db: AsyncSession, post: Post, viewer: User | None) -> None:
    is_own = viewer is not None and viewer.id == post.author_id
    if (post.moderation_state not in LIVE_STATES or post.author_hidden) and not is_own:
        raise not_found("Post")
    if viewer is not None and not is_own:
        ctx = await load_viewer_ctx(db, viewer)
        if post.author_id in ctx.blocked_ids:
            raise not_found("Post")


async def get_post(db: AsyncSession, post_id: uuid.UUID, viewer: User | None) -> AnyPostOut:
    post = await load_post(db, post_id)
    await ensure_visible(db, post, viewer)
    return (await hydrate(db, [post], viewer))[0]


# --- Tags --------------------------------------------------------------------------------------


async def adjust_tag_counts(db: AsyncSession, tags: Sequence[str], delta: int) -> None:
    if not tags:
        return
    stmt = insert(Tag).values([{"name": t, "post_count": max(delta, 0)} for t in set(tags)])
    stmt = stmt.on_conflict_do_update(
        index_elements=[Tag.name],
        set_={"post_count": Tag.post_count + delta},
    )
    await db.execute(stmt)


async def _on_published(db: AsyncSession, post: Post) -> None:
    """Side effects when a post becomes publicly visible (caller commits)."""
    await adjust_tag_counts(db, post.tags, 1)


async def _on_unpublished(db: AsyncSession, post: Post) -> None:
    await adjust_tag_counts(db, post.tags, -1)


async def _after_publish_commit(post: Post) -> None:
    if _URL.search(post.body):
        await enqueue("fetch_link_preview", str(post.id), job_id=f"link_preview:{post.id}")


# --- Create / update / delete ------------------------------------------------------------------


async def _attach_media(db: AsyncSession, user: User, media_ids: list[uuid.UUID]) -> list[Media]:
    if not media_ids:
        return []
    if len(set(media_ids)) != len(media_ids):
        raise bad_request("invalid_media", "Duplicate media")
    rows = (await db.scalars(select(Media).where(Media.id.in_(media_ids)).with_for_update())).all()
    by_id = {m.id: m for m in rows}
    ordered: list[Media] = []
    for mid in media_ids:
        media = by_id.get(mid)
        if (
            media is None
            or media.owner_id != user.id
            or media.purpose != MediaPurpose.post
            or media.post_id is not None
        ):
            raise not_found("Media")
        if media.state not in (MediaState.processing, MediaState.ready):
            raise bad_request("invalid_media", "Media was rejected or not uploaded")
        ordered.append(media)
    kinds = {m.kind for m in ordered}
    if MediaKind.video in kinds and len(ordered) > 1:
        raise bad_request("invalid_media", "A rant can have up to 4 images or 1 video")
    return ordered


async def _moderate(text: str) -> moderation.Verdict | None:
    """None means the moderation service is unavailable (caller must hold content back)."""
    try:
        verdict = await moderation.moderate_text(text)
    except moderation.ModerationUnavailableError:
        return None
    if verdict.action == "reject":
        raise AppError(
            422,
            "content_rejected",
            moderation.rejection_message(verdict),
            {"reasons": verdict.reasons},
        )
    return verdict


def _apply_verdict(post: Post, verdict: moderation.Verdict | None, media: list[Media]) -> None:
    if verdict is None:
        post.moderation_state = ModerationState.pending
        post.moderation_reason = "awaiting_moderation"
        return
    post.moderation = verdict.as_json()
    post.crisis_flag = post.crisis_flag or verdict.crisis
    if verdict.action == "review":
        post.moderation_state = ModerationState.in_review
        post.moderation_reason = ",".join(verdict.reasons)[:200]
    elif any(m.state != MediaState.ready for m in media):
        post.moderation_state = ModerationState.pending_media
    else:
        post.moderation_state = ModerationState.published


async def create_post(db: AsyncSession, user: User, data: PostCreateIn) -> AnyPostOut:
    anonymous = data.is_anonymous
    if anonymous is None:
        anonymous = (await load_settings(db, user.id)).privacy.default_anonymous
    media = await _attach_media(db, user, data.media_ids)
    verdict = await _moderate(f"{data.title}\n\n{data.body}")
    post = Post(
        id=uuid7(),
        author_id=user.id,
        is_anonymous=anonymous,
        title=data.title,
        body=data.body,
        category=data.category,
        tags=data.tags,
        frustration_level=data.frustration_level,
        status=data.status,
        content_warning=data.content_warning,
        moderation_state=ModerationState.pending,
    )
    _apply_verdict(post, verdict, media)
    db.add(post)
    await db.flush()
    for position, m in enumerate(media):
        m.post_id, m.position = post.id, position
    if post.moderation_state == ModerationState.published:
        await _on_published(db, post)
    await db.commit()
    if verdict is None:
        await enqueue(
            "moderate_post", str(post.id), job_id=f"moderate_post:{post.id}", defer_seconds=30
        )
    if post.moderation_state == ModerationState.published:
        await _after_publish_commit(post)
    from feed import invalidate_following_cache

    await invalidate_following_cache(user.id)
    return await get_post(db, post.id, user)


async def update_post(
    db: AsyncSession, user: User, post_id: uuid.UUID, data: PostUpdateIn
) -> AnyPostOut:
    post = await load_post(db, post_id, for_update=True)
    if post.author_id != user.id:
        raise forbidden("You can only edit your own rants")
    if post.moderation_state in (ModerationState.removed, ModerationState.rejected):
        raise forbidden("This rant was removed and can't be edited")
    content_fields = {"title", "body", "category", "tags", "frustration_level", "content_warning"}
    changes = data.model_dump(exclude_unset=True)
    if content_fields & changes.keys() and utcnow() - post.created_at > EDIT_WINDOW:
        raise AppError(403, "edit_window_closed", "Rants can be edited for 15 minutes")
    if "status" in changes and post.status == PostStatus.solved:
        raise bad_request("already_solved", "Unsolve the rant first")
    was_live = post.moderation_state == ModerationState.published
    old_tags = list(post.tags)
    text_changed = ("title" in changes and changes["title"] != post.title) or (
        "body" in changes and changes["body"] != post.body
    )
    for name, value in changes.items():
        if value is not None:
            setattr(post, name, value)
    if text_changed:
        verdict = await _moderate(f"{post.title}\n\n{post.body}")
        if verdict is None:
            post.moderation_state = ModerationState.pending
        elif verdict.action == "review":
            post.moderation_state = ModerationState.in_review
            post.moderation_reason = ",".join(verdict.reasons)[:200]
        post.crisis_flag = post.crisis_flag or bool(verdict and verdict.crisis)
        if verdict is not None:
            post.moderation = verdict.as_json()
        post.edited_at = utcnow()
    is_live = post.moderation_state == ModerationState.published
    if was_live:
        await adjust_tag_counts(db, old_tags, -1)
    if is_live:
        await adjust_tag_counts(db, post.tags, 1)
    await db.commit()
    if text_changed and post.moderation_state == ModerationState.pending:
        await enqueue(
            "moderate_post",
            str(post.id),
            job_id=f"moderate_post:{post.id}:{utcnow().timestamp()}",
            defer_seconds=30,
        )
    return await get_post(db, post.id, user)


async def delete_post(db: AsyncSession, user: User, post_id: uuid.UUID) -> None:
    post = await load_post(db, post_id, for_update=True)
    if post.author_id != user.id:
        raise forbidden("You can only delete your own rants")
    if post.moderation_state == ModerationState.published:
        await _on_unpublished(db, post)
    post.deleted_at = utcnow()
    await db.commit()
    await enqueue("delete_post_media", str(post.id))


# --- Reactions ---------------------------------------------------------------------------------


async def _live_post_for_interaction(db: AsyncSession, user: User, post_id: uuid.UUID) -> Post:
    post = await db.scalar(select(Post).where(Post.id == post_id, Post.deleted_at.is_(None)))
    if post is None or post.moderation_state != ModerationState.published or post.author_hidden:
        raise not_found("Post")
    ctx = await load_viewer_ctx(db, user)
    if post.author_id in ctx.blocked_ids:
        raise not_found("Post")
    return post


async def react(db: AsyncSession, user: User, post_id: uuid.UUID, kind: ReactionKind) -> AnyPostOut:
    post = await _live_post_for_interaction(db, user, post_id)
    existing: Reaction | None = None
    inserted = None
    for _ in range(2):  # a parallel request from the same user may insert first
        existing = await db.scalar(
            select(Reaction)
            .where(Reaction.post_id == post.id, Reaction.user_id == user.id)
            .with_for_update()
        )
        if existing is not None:
            break
        inserted = await db.scalar(
            insert(Reaction)
            .values(post_id=post.id, user_id=user.id, kind=kind)
            .on_conflict_do_nothing()
            .returning(Reaction.kind)
        )
        if inserted is not None:
            break
    if inserted is not None:
        await db.execute(
            update(Post)
            .where(Post.id == post.id)
            .values({REACTION_COLUMN[kind]: REACTION_COLUMN[kind] + 1})
        )
        await notify(
            db,
            user_id=post.author_id,
            type="reaction",
            actor_id=user.id,
            post_id=post.id,
            data={"kind": kind.value, "post_title": post.title[:80]},
            dedupe_key=f"reaction:{post.id}:{user.id}",
        )
    elif existing is not None and existing.kind != kind:
        old = existing.kind
        existing.kind = kind
        await db.execute(
            update(Post)
            .where(Post.id == post.id)
            .values(
                {
                    REACTION_COLUMN[old]: REACTION_COLUMN[old] - 1,
                    REACTION_COLUMN[kind]: REACTION_COLUMN[kind] + 1,
                }
            )
        )
    await db.commit()
    return await get_post(db, post.id, user)


async def unreact(db: AsyncSession, user: User, post_id: uuid.UUID) -> AnyPostOut:
    removed = await db.scalar(
        delete(Reaction)
        .where(Reaction.post_id == post_id, Reaction.user_id == user.id)
        .returning(Reaction.kind)
    )
    if removed is not None:
        kind = ReactionKind(removed)
        await db.execute(
            update(Post)
            .where(Post.id == post_id)
            .values({REACTION_COLUMN[kind]: REACTION_COLUMN[kind] - 1})
        )
    await db.commit()
    return await get_post(db, post_id, user)


# --- Solving -----------------------------------------------------------------------------------


async def _unpin(db: AsyncSession, post: Post) -> None:
    if post.pinned_comment_id is None:
        return
    old = await db.get(Comment, post.pinned_comment_id)
    if old is not None and old.author_id != post.author_id:
        await add_helper_score(db, old.author_id, -PINNED_ANSWER_POINTS)
    post.pinned_comment_id = None


async def solve(
    db: AsyncSession, user: User, post_id: uuid.UUID, comment_id: uuid.UUID | None
) -> AnyPostOut:
    post = await load_post(db, post_id, for_update=True)
    if post.author_id != user.id:
        raise forbidden("Only the author can mark a rant as solved")
    if post.moderation_state != ModerationState.published:
        raise bad_request("not_published", "Only published rants can be solved")
    comment: Comment | None = None
    if comment_id is not None:
        comment = await db.get(Comment, comment_id)
        if (
            comment is None
            or comment.post_id != post.id
            or comment.deleted_at is not None
            or comment.moderation_state != ModerationState.published
        ):
            raise not_found("Comment")
    if post.pinned_comment_id != comment_id:
        await _unpin(db, post)
        if comment is not None:
            post.pinned_comment_id = comment.id
            if comment.author_id != post.author_id:
                await add_helper_score(db, comment.author_id, PINNED_ANSWER_POINTS)
                await notify(
                    db,
                    user_id=comment.author_id,
                    type="solved",
                    actor_id=None if post.is_anonymous else user.id,
                    post_id=post.id,
                    comment_id=comment.id,
                    data={"post_title": post.title[:80]},
                    dedupe_key=f"solved:{post.id}:{comment.id}",
                )
    post.status = PostStatus.solved
    post.solved_at = post.solved_at or utcnow()
    await db.flush()
    await check_badges(db, user.id)
    if comment is not None and comment.author_id != user.id:
        await check_badges(db, comment.author_id)
    await db.commit()
    return await get_post(db, post.id, user)


async def unsolve(db: AsyncSession, user: User, post_id: uuid.UUID) -> AnyPostOut:
    post = await load_post(db, post_id, for_update=True)
    if post.author_id != user.id:
        raise forbidden("Only the author can change this")
    await _unpin(db, post)
    post.status = PostStatus.open
    post.solved_at = None
    await db.commit()
    return await get_post(db, post.id, user)


# --- Worker side -------------------------------------------------------------------------------


async def on_media_settled(post_id: uuid.UUID) -> None:
    """Called when one of a post's media finishes processing."""
    async with SessionLocal() as db:
        post = await db.scalar(select(Post).where(Post.id == post_id).with_for_update())
        if post is None or post.moderation_state != ModerationState.pending_media:
            return
        media = (
            await db.scalars(
                select(Media).where(Media.post_id == post_id, Media.state != MediaState.deleted)
            )
        ).all()
        if any(m.state == MediaState.processing for m in media):
            return
        flagged = [
            m
            for m in media
            if m.state == MediaState.rejected or (m.moderation or {}).get("action") == "review"
        ]
        if flagged:
            post.moderation_state = ModerationState.in_review
            post.moderation_reason = "media_flagged"
            if any(m.state == MediaState.rejected for m in flagged):
                await notify(
                    db,
                    user_id=post.author_id,
                    type="media_rejected",
                    post_id=post.id,
                    data={"post_title": post.title[:80]},
                    dedupe_key=f"media_rejected:{post.id}",
                )
        else:
            post.moderation_state = ModerationState.published
            await _on_published(db, post)
        await db.commit()
        if post.moderation_state == ModerationState.published:
            await _after_publish_commit(post)


async def remoderate_post(post_id: uuid.UUID) -> bool:
    """Retry moderation for posts held as `pending`. Returns False if still unavailable."""
    async with SessionLocal() as db:
        post = await db.scalar(select(Post).where(Post.id == post_id).with_for_update())
        if post is None or post.moderation_state != ModerationState.pending:
            return True
        try:
            verdict = await moderation.moderate_text(f"{post.title}\n\n{post.body}")
        except moderation.ModerationUnavailableError:
            return False
        media = (
            await db.scalars(
                select(Media).where(Media.post_id == post.id, Media.state != MediaState.deleted)
            )
        ).all()
        if verdict.action == "reject":
            post.moderation_state = ModerationState.rejected
            post.moderation_reason = ",".join(verdict.reasons)[:200]
            post.moderation = verdict.as_json()
            await notify(
                db,
                user_id=post.author_id,
                type="moderation",
                post_id=post.id,
                data={
                    "action": "rejected",
                    "post_title": post.title[:80],
                    "message": moderation.rejection_message(verdict),
                },
                dedupe_key=f"moderation:{post.id}",
            )
        else:
            _apply_verdict(post, verdict, list(media))
            if post.moderation_state == ModerationState.published:
                await _on_published(db, post)
        await db.commit()
        if post.moderation_state == ModerationState.published:
            await _after_publish_commit(post)
        return True
