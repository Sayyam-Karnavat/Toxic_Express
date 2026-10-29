"""Moderator toolkit: review queue, actions (approve/remove/strike/suspend/ban), audit, appeals."""

import uuid
from datetime import timedelta

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from errors import AppError, bad_request, conflict, forbidden, not_found
from models import (
    Appeal,
    AppealStatus,
    Comment,
    EntityType,
    ModerationAction,
    ModerationState,
    Post,
    Report,
    ReportStatus,
    Role,
    Strike,
    User,
    UserStatus,
)
from notifications_service import notify
from schemas import (
    AppealIn,
    AppealOut,
    AppealPage,
    AuditPage,
    ModActionIn,
    ModActionOut,
    QueueItemOut,
    QueueOut,
)
from tasks import enqueue
from users_service import set_author_hidden, user_summary
from utils import decode_cursor, encode_cursor, keyset_before, utcnow

STRIKE_TTL = timedelta(days=90)
STRIKES_FOR_SUSPENSION = 3
AUTO_SUSPENSION = timedelta(days=7)
APPEAL_WINDOW = timedelta(days=30)
REVIEWABLE = (ModerationState.in_review, ModerationState.pending)


async def _open_reports(
    db: AsyncSession, entity_type: EntityType, ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, list[str]]]:
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(Report.entity_id, func.count(), func.array_agg(func.distinct(Report.reason)))
            .where(
                Report.entity_type == entity_type,
                Report.entity_id.in_(ids),
                Report.status == ReportStatus.open,
            )
            .group_by(Report.entity_id)
        )
    ).all()
    return {eid: (count, [str(r) for r in reasons]) for eid, count, reasons in rows}


async def queue(db: AsyncSession) -> QueueOut:
    reported_posts = select(Report.entity_id).where(
        Report.entity_type == EntityType.post, Report.status == ReportStatus.open
    )
    posts = (
        await db.scalars(
            select(Post)
            .options(selectinload(Post.author))
            .where(
                Post.deleted_at.is_(None),
                or_(Post.moderation_state.in_(REVIEWABLE), Post.id.in_(reported_posts)),
            )
            .order_by(Post.report_weight.desc(), Post.created_at)
            .limit(50)
        )
    ).all()
    reported_comments = select(Report.entity_id).where(
        Report.entity_type == EntityType.comment, Report.status == ReportStatus.open
    )
    comments = (
        await db.scalars(
            select(Comment)
            .options(selectinload(Comment.author))
            .where(
                Comment.deleted_at.is_(None),
                or_(Comment.moderation_state.in_(REVIEWABLE), Comment.id.in_(reported_comments)),
            )
            .order_by(Comment.report_weight.desc(), Comment.created_at)
            .limit(50)
        )
    ).all()
    reported_users = (
        await db.scalars(
            select(User)
            .where(
                User.id.in_(
                    select(Report.entity_id).where(
                        Report.entity_type == EntityType.user, Report.status == ReportStatus.open
                    )
                )
            )
            .limit(50)
        )
    ).all()

    post_reports = await _open_reports(db, EntityType.post, [p.id for p in posts])
    comment_reports = await _open_reports(db, EntityType.comment, [c.id for c in comments])
    user_reports = await _open_reports(db, EntityType.user, [u.id for u in reported_users])
    items: list[QueueItemOut] = []
    for p in posts:
        count, reasons = post_reports.get(p.id, (0, []))
        items.append(
            QueueItemOut(
                entity_type=EntityType.post,
                entity_id=p.id,
                moderation_state=p.moderation_state,
                moderation_reason=p.moderation_reason,
                title=p.title,
                body=p.body,
                is_anonymous=p.is_anonymous,
                author=user_summary(p.author),
                report_count=count,
                report_weight=p.report_weight,
                report_reasons=reasons,
                flags=p.moderation,
                created_at=p.created_at,
            )
        )
    for c in comments:
        count, reasons = comment_reports.get(c.id, (0, []))
        items.append(
            QueueItemOut(
                entity_type=EntityType.comment,
                entity_id=c.id,
                moderation_state=c.moderation_state,
                moderation_reason=None,
                title=None,
                body=c.body,
                is_anonymous=c.is_anonymous,
                author=user_summary(c.author),
                report_count=count,
                report_weight=c.report_weight,
                report_reasons=reasons,
                flags=c.moderation,
                created_at=c.created_at,
            )
        )
    for u in reported_users:
        count, reasons = user_reports.get(u.id, (0, []))
        items.append(
            QueueItemOut(
                entity_type=EntityType.user,
                entity_id=u.id,
                moderation_state=None,
                moderation_reason=None,
                title=u.display_name,
                body=u.bio,
                is_anonymous=False,
                author=user_summary(u),
                report_count=count,
                report_weight=float(count),
                report_reasons=reasons,
                flags=None,
                created_at=u.created_at,
            )
        )
    items.sort(key=lambda i: (-i.report_weight, i.created_at))
    return QueueOut(items=items, next_cursor=None)


async def _resolve_reports(
    db: AsyncSession, mod: User, entity_type: EntityType, entity_id: uuid.UUID, status: ReportStatus
) -> None:
    await db.execute(
        update(Report)
        .where(
            Report.entity_type == entity_type,
            Report.entity_id == entity_id,
            Report.status == ReportStatus.open,
        )
        .values(status=status, resolved_by=mod.id, resolved_at=utcnow())
    )


async def _set_post_state(db: AsyncSession, post: Post, state: ModerationState) -> None:
    from posts_service import _on_published, _on_unpublished

    was_live = post.moderation_state == ModerationState.published
    post.moderation_state = state
    if state == ModerationState.published:
        post.report_weight = 0
        if not was_live:
            await _on_published(db, post)
    elif was_live:
        await _on_unpublished(db, post)


async def _set_comment_state(db: AsyncSession, comment: Comment, state: ModerationState) -> None:
    from comments_service import _adjust_counts_on_hide

    was_live = comment.moderation_state == ModerationState.published
    comment.moderation_state = state
    if state == ModerationState.published:
        comment.report_weight = 0
        if not was_live:
            await db.execute(
                update(Post)
                .where(Post.id == comment.post_id)
                .values(comment_count=Post.comment_count + 1)
            )
            if comment.parent_id:
                await db.execute(
                    update(Comment)
                    .where(Comment.id == comment.parent_id)
                    .values(reply_count=Comment.reply_count + 1)
                )
    elif was_live:
        await _adjust_counts_on_hide(db, comment)


async def _apply_user_action(
    db: AsyncSession,
    mod: User,
    target: User,
    action: str,
    days: int,
    reason: str,
    action_id: uuid.UUID,
) -> None:
    from auth_service import revoke_all_sessions

    if target.role != Role.user and mod.role != Role.admin:
        raise forbidden("Only admins can act on staff accounts")
    if target.id == mod.id:
        raise bad_request("invalid_target", "You can't moderate yourself")
    if action == "strike":
        db.add(
            Strike(
                user_id=target.id,
                action_id=action_id,
                reason=reason,
                expires_at=utcnow() + STRIKE_TTL,
            )
        )
        await db.flush()
        active = (
            await db.scalar(
                select(func.count())
                .select_from(Strike)
                .where(Strike.user_id == target.id, Strike.expires_at > utcnow())
            )
            or 0
        )
        if active >= STRIKES_FOR_SUSPENSION and target.status == UserStatus.active:
            target.status = UserStatus.suspended
            target.suspended_until = utcnow() + AUTO_SUSPENSION
    elif action == "suspend":
        target.status = UserStatus.suspended
        target.suspended_until = utcnow() + timedelta(days=days)
    elif action == "ban":
        if mod.role != Role.admin:
            raise forbidden("Only admins can ban accounts")
        target.status = UserStatus.banned
        await revoke_all_sessions(db, target.id)
        await set_author_hidden(db, target.id, True)
    elif action == "unban":
        if mod.role != Role.admin:
            raise forbidden("Only admins can lift bans")
        target.status = UserStatus.active
        target.suspended_until = None
        await set_author_hidden(db, target.id, False)


async def act(db: AsyncSession, mod: User, data: ModActionIn) -> ModActionOut:
    post: Post | None = None
    comment: Comment | None = None
    target: User | None
    if data.entity_type == EntityType.post:
        post = await db.scalar(select(Post).where(Post.id == data.entity_id).with_for_update())
        if post is None:
            raise not_found("Post")
        target = await db.get(User, post.author_id)
    elif data.entity_type == EntityType.comment:
        comment = await db.scalar(
            select(Comment).where(Comment.id == data.entity_id).with_for_update()
        )
        if comment is None:
            raise not_found("Comment")
        target = await db.get(User, comment.author_id)
    else:
        target = await db.get(User, data.entity_id)
        if target is None:
            raise not_found("User")
    assert target is not None

    record = ModerationAction(
        moderator_id=mod.id,
        target_user_id=target.id,
        entity_type=data.entity_type,
        entity_id=data.entity_id,
        action=data.action,
        reason=data.reason,
    )
    db.add(record)
    await db.flush()

    if data.action in ("approve", "restore", "remove"):
        if post is None and comment is None:
            raise bad_request("invalid_action", "This action applies to posts and comments")
        new_state = (
            ModerationState.removed if data.action == "remove" else ModerationState.published
        )
        if post is not None:
            await _set_post_state(db, post, new_state)
        if comment is not None:
            await _set_comment_state(db, comment, new_state)
        await _resolve_reports(
            db,
            mod,
            data.entity_type,
            data.entity_id,
            ReportStatus.actioned if data.action == "remove" else ReportStatus.dismissed,
        )
    elif data.action == "dismiss_reports":
        await _resolve_reports(db, mod, data.entity_type, data.entity_id, ReportStatus.dismissed)
        if post is not None:
            post.report_weight = 0
        if comment is not None:
            comment.report_weight = 0
    else:
        await _apply_user_action(
            db, mod, target, data.action, data.suspend_days, data.reason, record.id
        )
        await _resolve_reports(db, mod, data.entity_type, data.entity_id, ReportStatus.actioned)

    if data.action in ("remove", "strike", "suspend", "ban"):
        await notify(
            db,
            user_id=target.id,
            type="moderation",
            post_id=post.id if post else (comment.post_id if comment else None),
            comment_id=comment.id if comment else None,
            data={
                "action": data.action,
                "reason": data.reason,
                "action_id": str(record.id),
                "appealable": True,
            },
            dedupe_key=f"moderation:{record.id}",
        )
    await db.commit()
    if data.action == "remove" and post is not None:
        await enqueue("delete_post_media", str(post.id))
    return ModActionOut.model_validate(record)


async def audit(db: AsyncSession, cursor: str | None, limit: int = 50) -> AuditPage:
    query = (
        select(ModerationAction)
        .order_by(ModerationAction.created_at.desc(), ModerationAction.id.desc())
        .limit(limit + 1)
    )
    position = decode_cursor(cursor)
    if position:
        query = query.where(
            keyset_before(ModerationAction.created_at, ModerationAction.id, position)
        )
    rows = list((await db.scalars(query)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return AuditPage(
        items=[ModActionOut.model_validate(r) for r in rows],
        next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None,
    )


async def my_actions(db: AsyncSession, user: User) -> list[ModActionOut]:
    rows = (
        await db.scalars(
            select(ModerationAction)
            .where(
                ModerationAction.target_user_id == user.id,
                ModerationAction.action.in_(["remove", "strike", "suspend", "ban"]),
            )
            .order_by(ModerationAction.created_at.desc())
            .limit(50)
        )
    ).all()
    return [ModActionOut.model_validate(r) for r in rows]


async def create_appeal(db: AsyncSession, user: User, data: AppealIn) -> AppealOut:
    action = await db.get(ModerationAction, data.action_id)
    if action is None or action.target_user_id != user.id:
        raise not_found("Moderation action")
    if utcnow() - action.created_at > APPEAL_WINDOW:
        raise AppError(400, "appeal_window_closed", "Appeals must be filed within 30 days")
    existing = await db.scalar(select(Appeal).where(Appeal.action_id == action.id))
    if existing is not None:
        raise conflict("already_appealed", "You already appealed this decision")
    appeal = Appeal(user_id=user.id, action_id=action.id, message=data.message)
    db.add(appeal)
    await db.commit()
    return AppealOut.model_validate(appeal)


async def list_appeals(db: AsyncSession, cursor: str | None, limit: int = 50) -> AppealPage:
    query = (
        select(Appeal)
        .where(Appeal.status == AppealStatus.open)
        .order_by(Appeal.created_at.desc(), Appeal.id.desc())
        .limit(limit + 1)
    )
    position = decode_cursor(cursor)
    if position:
        query = query.where(keyset_before(Appeal.created_at, Appeal.id, position))
    rows = list((await db.scalars(query)).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return AppealPage(
        items=[AppealOut.model_validate(r) for r in rows],
        next_cursor=encode_cursor(rows[-1].created_at, rows[-1].id) if has_more and rows else None,
    )


async def resolve_appeal(
    db: AsyncSession, mod: User, appeal_id: uuid.UUID, accept: bool, note: str
) -> AppealOut:
    appeal = await db.scalar(select(Appeal).where(Appeal.id == appeal_id).with_for_update())
    if appeal is None:
        raise not_found("Appeal")
    if appeal.status != AppealStatus.open:
        raise conflict("already_resolved", "This appeal was already resolved")
    action = await db.get(ModerationAction, appeal.action_id)
    assert action is not None
    if accept:
        if action.action == "remove":
            if action.entity_type == EntityType.post:
                post = await db.get(Post, action.entity_id)
                if post is not None:
                    await _set_post_state(db, post, ModerationState.published)
            elif action.entity_type == EntityType.comment:
                comment = await db.get(Comment, action.entity_id)
                if comment is not None:
                    await _set_comment_state(db, comment, ModerationState.published)
        elif action.action == "strike":
            await db.execute(
                update(Strike).where(Strike.action_id == action.id).values(expires_at=utcnow())
            )
        elif action.action in ("suspend", "ban"):
            target = await db.get(User, appeal.user_id)
            if target is not None and target.status in (UserStatus.suspended, UserStatus.banned):
                target.status = UserStatus.active
                target.suspended_until = None
                await set_author_hidden(db, target.id, False)
    appeal.status = AppealStatus.accepted if accept else AppealStatus.rejected
    appeal.resolved_by = mod.id
    appeal.resolved_at = utcnow()
    db.add(
        ModerationAction(
            moderator_id=mod.id,
            target_user_id=appeal.user_id,
            entity_type=action.entity_type,
            entity_id=action.entity_id,
            action="appeal_accepted" if accept else "appeal_rejected",
            reason=note,
        )
    )
    await notify(
        db,
        user_id=appeal.user_id,
        type="appeal",
        data={"accepted": accept, "note": note, "action_id": str(action.id)},
        dedupe_key=f"appeal:{appeal.id}",
    )
    await db.commit()
    return AppealOut.model_validate(appeal)
