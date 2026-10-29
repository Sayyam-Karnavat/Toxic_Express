"""Helper Score and badges."""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import Comment, CommentFlair, ModerationState, Post, PostStatus, User, UserBadge
from notifications_service import notify

HELPFUL_VOTE_POINTS = 1
PINNED_ANSWER_POINTS = 10

BADGES = {
    "problem_solver": "Problem Solver: 5 of your comments were pinned as the answer",
    "survivor": "Survivor: marked 5 of your own rants as solved",
    "good_listener": "Good Listener: left 25 supportive comments",
    "helpful_hand": "Helpful Hand: reached a Helper Score of 50",
}


async def add_helper_score(db: AsyncSession, user_id: uuid.UUID, points: int) -> None:
    await db.execute(
        update(User)
        .where(User.id == user_id)
        .values(helper_score=func.greatest(User.helper_score + points, 0))
    )


async def _award(db: AsyncSession, user_id: uuid.UUID, badge: str) -> None:
    inserted = await db.scalar(
        insert(UserBadge)
        .values(user_id=user_id, badge=badge)
        .on_conflict_do_nothing()
        .returning(UserBadge.badge)
    )
    if inserted:
        await notify(
            db,
            user_id=user_id,
            type="badge",
            data={"badge": badge, "description": BADGES[badge]},
            dedupe_key=f"badge:{badge}",
        )


async def check_badges(db: AsyncSession, user_id: uuid.UUID) -> None:
    """Cheap aggregate checks; called after events that can earn a badge."""
    live = (Post.moderation_state == ModerationState.published, Post.deleted_at.is_(None))
    pinned = (
        await db.scalar(
            select(func.count())
            .select_from(Post)
            .join(Comment, Comment.id == Post.pinned_comment_id)
            .where(Comment.author_id == user_id, Post.author_id != user_id, *live)
        )
        or 0
    )
    solved = (
        await db.scalar(
            select(func.count())
            .select_from(Post)
            .where(Post.author_id == user_id, Post.status == PostStatus.solved, *live)
        )
        or 0
    )
    supportive = (
        await db.scalar(
            select(func.count())
            .select_from(Comment)
            .where(
                Comment.author_id == user_id,
                Comment.flair == CommentFlair.support,
                Comment.deleted_at.is_(None),
            )
        )
        or 0
    )
    score = await db.scalar(select(User.helper_score).where(User.id == user_id)) or 0
    if pinned >= 5:
        await _award(db, user_id, "problem_solver")
    if solved >= 5:
        await _award(db, user_id, "survivor")
    if supportive >= 25:
        await _award(db, user_id, "good_listener")
    if score >= 50:
        await _award(db, user_id, "helpful_hand")
