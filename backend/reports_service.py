"""User reports. Weighted reports auto-hide content pending moderator review."""

from datetime import timedelta

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from errors import bad_request, not_found
from models import (
    Comment,
    EntityType,
    ModerationState,
    Post,
    Report,
    ReportReason,
    User,
    UserStatus,
)
from schemas import ReportIn
from utils import utcnow

AUTO_HIDE_WEIGHT = 3.0


def report_weight(reporter: User) -> float:
    trusted = reporter.email_verified_at is not None and utcnow() - reporter.created_at > timedelta(
        days=7
    )
    return 1.0 if trusted else 0.5


async def create_report(db: AsyncSession, reporter: User, data: ReportIn) -> None:
    target_owner = None
    entity: Post | Comment | User | None
    if data.entity_type == EntityType.post:
        entity = await db.get(Post, data.entity_id)
        if entity is None or entity.deleted_at is not None:
            raise not_found("Post")
        target_owner = entity.author_id
    elif data.entity_type == EntityType.comment:
        entity = await db.get(Comment, data.entity_id)
        if entity is None or entity.deleted_at is not None:
            raise not_found("Comment")
        target_owner = entity.author_id
    else:
        entity = await db.get(User, data.entity_id)
        if entity is None or entity.status in (UserStatus.banned, UserStatus.deleted):
            raise not_found("User")
        target_owner = entity.id
    if target_owner == reporter.id:
        raise bad_request("own_content", "You can't report yourself")

    weight = report_weight(reporter)
    inserted = await db.scalar(
        insert(Report)
        .values(
            reporter_id=reporter.id,
            entity_type=data.entity_type,
            entity_id=data.entity_id,
            reason=data.reason,
            note=data.note,
            weight=weight,
        )
        .on_conflict_do_nothing()
        .returning(Report.id)
    )
    if inserted is None:  # already reported by this user: idempotent
        await db.commit()
        return

    if isinstance(entity, Post):
        if data.reason == ReportReason.self_harm:
            entity.crisis_flag = True  # surface support resources right away
        new_weight = await db.scalar(
            update(Post)
            .where(Post.id == entity.id)
            .values(report_weight=Post.report_weight + weight)
            .returning(Post.report_weight)
        )
        if (
            new_weight or 0
        ) >= AUTO_HIDE_WEIGHT and entity.moderation_state == ModerationState.published:
            from posts_service import _on_unpublished

            entity.moderation_state = ModerationState.in_review
            entity.moderation_reason = "community_reports"
            await _on_unpublished(db, entity)
    elif isinstance(entity, Comment):
        new_weight = await db.scalar(
            update(Comment)
            .where(Comment.id == entity.id)
            .values(report_weight=Comment.report_weight + weight)
            .returning(Comment.report_weight)
        )
        if (
            new_weight or 0
        ) >= AUTO_HIDE_WEIGHT and entity.moderation_state == ModerationState.published:
            from comments_service import _adjust_counts_on_hide

            entity.moderation_state = ModerationState.in_review
            await _adjust_counts_on_hide(db, entity)
    await db.commit()
