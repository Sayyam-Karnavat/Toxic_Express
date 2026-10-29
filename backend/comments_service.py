"""Comments: 2-level threads, flairs, helpful votes, anonymous-OP handling and moderation."""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import moderation
from database import SessionLocal
from errors import AppError, bad_request, forbidden, not_found
from models import Comment, CommentVote, Follow, ModerationState, Post, User
from notifications_service import notify
from posts_service import _moderate, ensure_visible, load_post
from reputation import HELPFUL_VOTE_POINTS, add_helper_score, check_badges
from schemas import (
    AnonCommentOut,
    AnyCommentOut,
    CommentCreateIn,
    CommentOut,
    CommentPage,
    CommentUpdateIn,
)
from social_service import ViewerContext, load_viewer_ctx
from tasks import enqueue
from users_service import load_settings, user_summary
from utils import decode_cursor, encode_cursor, keyset_after, utcnow, uuid7

EDIT_WINDOW = timedelta(minutes=15)
REPLIES_PREVIEW = 3
DELETED_BODY = "[deleted]"


def _visible_filter(viewer: User | None, ctx: ViewerContext):
    """Published comments (or the viewer's own), hiding blocked/muted authors."""
    visible = Comment.moderation_state == ModerationState.published
    if viewer is not None:
        visible = or_(visible, Comment.author_id == viewer.id)
    clauses = [visible, Comment.author_hidden.is_(False)]
    if ctx.hidden_author_ids:
        clauses.append(Comment.author_id.not_in(ctx.hidden_author_ids))
    # Deleted comments only stay as "[deleted]" placeholders when they have replies.
    clauses.append(or_(Comment.deleted_at.is_(None), Comment.reply_count > 0))
    return and_(*clauses)


async def _hydrate(
    db: AsyncSession,
    comments: Sequence[Comment],
    post: Post,
    viewer: User | None,
    replies: dict[uuid.UUID, list[Comment]] | None = None,
) -> list[AnyCommentOut]:
    all_ids = [c.id for c in comments] + [r.id for rs in (replies or {}).values() for r in rs]
    voted: set[uuid.UUID] = set()
    if viewer is not None and all_ids:
        voted = set(
            (
                await db.scalars(
                    select(CommentVote.comment_id).where(
                        CommentVote.user_id == viewer.id, CommentVote.comment_id.in_(all_ids)
                    )
                )
            ).all()
        )

    def build(c: Comment) -> AnyCommentOut:
        deleted = c.deleted_at is not None
        common = {
            "id": c.id,
            "post_id": c.post_id,
            "parent_id": c.parent_id,
            "body": DELETED_BODY if deleted else c.body,
            "flair": c.flair,
            "helpful_count": c.helpful_count,
            "my_helpful": c.id in voted,
            "reply_count": c.reply_count,
            "is_op": c.author_id == post.author_id,
            "is_pinned": c.id == post.pinned_comment_id,
            "is_own": viewer is not None and viewer.id == c.author_id and not deleted,
            "deleted": deleted,
            "moderation_state": c.moderation_state,
            "created_at": c.created_at,
            "edited_at": c.edited_at,
            "replies": [build(r) for r in (replies or {}).get(c.id, [])],
        }
        if c.is_anonymous:
            return AnonCommentOut(**common)
        return CommentOut(**common, author=None if deleted else user_summary(c.author))

    return [build(c) for c in comments]


async def list_comments(
    db: AsyncSession, post_id: uuid.UUID, viewer: User | None, cursor: str | None, limit: int = 20
) -> CommentPage:
    post = await load_post(db, post_id)
    await ensure_visible(db, post, viewer)
    ctx = await load_viewer_ctx(db, viewer)
    query = (
        select(Comment)
        .options(selectinload(Comment.author))
        .where(
            Comment.post_id == post.id, Comment.parent_id.is_(None), _visible_filter(viewer, ctx)
        )
        .order_by(Comment.created_at, Comment.id)
        .limit(limit + 1)
    )
    position = decode_cursor(cursor)
    if position:
        query = query.where(keyset_after(Comment.created_at, Comment.id, position))
    top = list((await db.scalars(query)).all())
    has_more = len(top) > limit
    top = top[:limit]

    replies: dict[uuid.UUID, list[Comment]] = defaultdict(list)
    parents = [c.id for c in top if c.reply_count > 0]
    if parents:
        ranked = (
            select(
                Comment.id,
                func.row_number()
                .over(partition_by=Comment.parent_id, order_by=(Comment.created_at, Comment.id))
                .label("rn"),
            )
            .where(Comment.parent_id.in_(parents), _visible_filter(viewer, ctx))
            .subquery()
        )
        rows = (
            await db.scalars(
                select(Comment)
                .options(selectinload(Comment.author))
                .join(ranked, ranked.c.id == Comment.id)
                .where(ranked.c.rn <= REPLIES_PREVIEW)
                .order_by(Comment.created_at, Comment.id)
            )
        ).all()
        for r in rows:
            assert r.parent_id is not None
            replies[r.parent_id].append(r)
    items = await _hydrate(db, top, post, viewer, replies)
    next_cursor = encode_cursor(top[-1].created_at, top[-1].id) if has_more and top else None
    return CommentPage(items=items, next_cursor=next_cursor)


async def list_replies(
    db: AsyncSession,
    comment_id: uuid.UUID,
    viewer: User | None,
    cursor: str | None,
    limit: int = 20,
) -> CommentPage:
    parent = await db.get(Comment, comment_id)
    if parent is None:
        raise not_found("Comment")
    post = await load_post(db, parent.post_id)
    await ensure_visible(db, post, viewer)
    ctx = await load_viewer_ctx(db, viewer)
    query = (
        select(Comment)
        .options(selectinload(Comment.author))
        .where(Comment.parent_id == parent.id, _visible_filter(viewer, ctx))
        .order_by(Comment.created_at, Comment.id)
        .limit(limit + 1)
    )
    position = decode_cursor(cursor)
    if position:
        query = query.where(keyset_after(Comment.created_at, Comment.id, position))
    rows = list((await db.scalars(query)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    items = await _hydrate(db, rows, post, viewer)
    next_cursor = encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None
    return CommentPage(items=items, next_cursor=next_cursor)


async def get_comment(
    db: AsyncSession, comment_id: uuid.UUID, viewer: User | None
) -> AnyCommentOut:
    comment = await db.scalar(
        select(Comment)
        .options(selectinload(Comment.author))
        .where(Comment.id == comment_id)
        .execution_options(populate_existing=True)
    )
    if comment is None:
        raise not_found("Comment")
    post = await load_post(db, comment.post_id)
    await ensure_visible(db, post, viewer)
    is_own = viewer is not None and viewer.id == comment.author_id
    if comment.moderation_state != ModerationState.published and not is_own:
        raise not_found("Comment")
    ctx = await load_viewer_ctx(db, viewer)
    if comment.author_id in ctx.blocked_ids:
        raise not_found("Comment")
    return (await _hydrate(db, [comment], post, viewer))[0]


async def _can_comment(db: AsyncSession, post: Post, user: User) -> None:
    if user.id == post.author_id:
        return
    ctx = await load_viewer_ctx(db, user)
    if post.author_id in ctx.blocked_ids:
        raise forbidden("Comments are limited on this rant")
    who = (await load_settings(db, post.author_id)).privacy.who_can_comment
    if who == "none":
        raise forbidden("Comments are limited on this rant")
    if who == "followers" and not await db.scalar(
        select(exists().where(Follow.follower_id == user.id, Follow.followee_id == post.author_id))
    ):
        raise forbidden("Only followers can comment on this rant")


async def create_comment(
    db: AsyncSession, user: User, post_id: uuid.UUID, data: CommentCreateIn
) -> AnyCommentOut:
    post = await load_post(db, post_id)
    if post.moderation_state != ModerationState.published:
        raise not_found("Post")
    await _can_comment(db, post, user)
    parent: Comment | None = None
    if data.parent_id is not None:
        parent = await db.get(Comment, data.parent_id)
        if (
            parent is None
            or parent.post_id != post.id
            or (
                parent.deleted_at is not None
                and parent.parent_id is None
                and parent.reply_count == 0
            )
        ):
            raise not_found("Comment")
        if parent.parent_id is not None:  # keep threads two levels deep
            parent = await db.get(Comment, parent.parent_id)
            assert parent is not None
    verdict = await _moderate(data.body)
    comment = Comment(
        id=uuid7(),
        post_id=post.id,
        author_id=user.id,
        parent_id=parent.id if parent else None,
        body=data.body,
        flair=data.flair,
        is_anonymous=post.is_anonymous and user.id == post.author_id,
        moderation_state=ModerationState.pending,
    )
    if verdict is not None:
        comment.moderation = verdict.as_json()
        comment.moderation_state = (
            ModerationState.in_review if verdict.action == "review" else ModerationState.published
        )
    db.add(comment)
    await db.flush()
    if comment.moderation_state == ModerationState.published:
        await _on_comment_published(db, comment, post, parent)
    await db.commit()
    if verdict is None:
        await enqueue(
            "moderate_comment",
            str(comment.id),
            job_id=f"moderate_comment:{comment.id}",
            defer_seconds=30,
        )
    return await get_comment(db, comment.id, user)


async def _on_comment_published(
    db: AsyncSession, comment: Comment, post: Post, parent: Comment | None
) -> None:
    await db.execute(
        update(Post).where(Post.id == post.id).values(comment_count=Post.comment_count + 1)
    )
    actor = None if comment.is_anonymous else comment.author_id
    data = {"post_title": post.title[:80], "snippet": comment.body[:120]}
    if parent is not None:
        await db.execute(
            update(Comment)
            .where(Comment.id == parent.id)
            .values(reply_count=Comment.reply_count + 1)
        )
        if parent.author_id != post.author_id:
            await notify(
                db,
                user_id=parent.author_id,
                type="reply",
                actor_id=actor,
                post_id=post.id,
                comment_id=comment.id,
                data=data,
                dedupe_key=f"reply:{comment.id}",
            )
    if comment.author_id != post.author_id:
        await notify(
            db,
            user_id=post.author_id,
            type="comment",
            actor_id=actor,
            post_id=post.id,
            comment_id=comment.id,
            data=data,
            dedupe_key=f"comment:{comment.id}",
        )
    await check_badges(db, comment.author_id)


async def update_comment(
    db: AsyncSession, user: User, comment_id: uuid.UUID, data: CommentUpdateIn
) -> AnyCommentOut:
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id).with_for_update())
    if comment is None or comment.deleted_at is not None:
        raise not_found("Comment")
    if comment.author_id != user.id:
        raise forbidden("You can only edit your own comments")
    if comment.moderation_state in (ModerationState.removed, ModerationState.rejected):
        raise forbidden("This comment was removed")
    if utcnow() - comment.created_at > EDIT_WINDOW:
        raise AppError(403, "edit_window_closed", "Comments can be edited for 15 minutes")
    if data.body != comment.body:
        verdict = await _moderate(data.body)
        comment.body = data.body
        comment.edited_at = utcnow()
        if verdict is None:
            raise AppError(503, "moderation_unavailable", "Please try again in a moment")
        comment.moderation = verdict.as_json()
        if verdict.action == "review" and comment.moderation_state == ModerationState.published:
            comment.moderation_state = ModerationState.in_review
            await _adjust_counts_on_hide(db, comment)
    await db.commit()
    return await get_comment(db, comment.id, user)


async def _adjust_counts_on_hide(db: AsyncSession, comment: Comment) -> None:
    await db.execute(
        update(Post)
        .where(Post.id == comment.post_id)
        .values(comment_count=func.greatest(Post.comment_count - 1, 0))
    )
    if comment.parent_id is not None:
        await db.execute(
            update(Comment)
            .where(Comment.id == comment.parent_id)
            .values(reply_count=func.greatest(Comment.reply_count - 1, 0))
        )
    post = await db.get(Post, comment.post_id)
    if post is not None and post.pinned_comment_id == comment.id:
        from posts_service import _unpin

        await _unpin(db, post)


async def delete_comment(db: AsyncSession, user: User, comment_id: uuid.UUID) -> None:
    comment = await db.scalar(select(Comment).where(Comment.id == comment_id).with_for_update())
    if comment is None or comment.deleted_at is not None:
        raise not_found("Comment")
    if comment.author_id != user.id:
        raise forbidden("You can only delete your own comments")
    if comment.moderation_state == ModerationState.published:
        await _adjust_counts_on_hide(db, comment)
    comment.deleted_at = utcnow()
    await db.commit()


async def set_helpful(
    db: AsyncSession, user: User, comment_id: uuid.UUID, helpful: bool
) -> AnyCommentOut:
    comment = await db.get(Comment, comment_id)
    if (
        comment is None
        or comment.deleted_at is not None
        or comment.moderation_state != ModerationState.published
    ):
        raise not_found("Comment")
    if comment.author_id == user.id:
        raise bad_request("own_comment", "You can't vote on your own comment")
    post = await load_post(db, comment.post_id)
    await ensure_visible(db, post, user)
    if helpful:
        changed = await db.scalar(
            insert(CommentVote)
            .values(comment_id=comment.id, user_id=user.id)
            .on_conflict_do_nothing()
            .returning(CommentVote.comment_id)
        )
        delta = 1
    else:
        changed = await db.scalar(
            delete(CommentVote)
            .where(CommentVote.comment_id == comment.id, CommentVote.user_id == user.id)
            .returning(CommentVote.comment_id)
        )
        delta = -1
    if changed:
        await db.execute(
            update(Comment)
            .where(Comment.id == comment.id)
            .values(helpful_count=func.greatest(Comment.helpful_count + delta, 0))
        )
        await add_helper_score(db, comment.author_id, delta * HELPFUL_VOTE_POINTS)
        if helpful:
            await notify(
                db,
                user_id=comment.author_id,
                type="helpful",
                actor_id=user.id,
                post_id=post.id,
                comment_id=comment.id,
                data={"snippet": comment.body[:120]},
                dedupe_key=f"helpful:{comment.id}",
            )
            await check_badges(db, comment.author_id)
    await db.commit()
    return await get_comment(db, comment.id, user)


async def remoderate_comment(comment_id: uuid.UUID) -> bool:
    async with SessionLocal() as db:
        comment = await db.scalar(select(Comment).where(Comment.id == comment_id).with_for_update())
        if comment is None or comment.moderation_state != ModerationState.pending:
            return True
        try:
            verdict = await moderation.moderate_text(comment.body)
        except moderation.ModerationUnavailableError:
            return False
        comment.moderation = verdict.as_json()
        if verdict.action == "reject":
            comment.moderation_state = ModerationState.rejected
        elif verdict.action == "review":
            comment.moderation_state = ModerationState.in_review
        else:
            comment.moderation_state = ModerationState.published
            post = await db.get(Post, comment.post_id)
            parent = await db.get(Comment, comment.parent_id) if comment.parent_id else None
            if post is not None:
                await _on_comment_published(db, comment, post, parent)
        await db.commit()
        return True
