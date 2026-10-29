"""Profiles, settings, onboarding, account deletion and data export."""

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import and_, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from errors import AppError, bad_request, conflict, not_found
from models import (
    Block,
    Comment,
    Follow,
    Media,
    MediaPurpose,
    MediaState,
    ModerationState,
    Mute,
    OAuthAccount,
    Post,
    PostStatus,
    Reaction,
    User,
    UserBadge,
    UserSettings,
    UserStatus,
)
from schemas import (
    ContentSettings,
    MeOut,
    NotificationSettings,
    OnboardingIn,
    PrivacySettings,
    ProfileOut,
    ProfileUpdateIn,
    SettingsOut,
    SettingsPatchIn,
    UserSummary,
)
from storage import public_urls
from utils import utcnow

HANDLE_CHANGE_COOLDOWN = timedelta(days=30)
DELETION_GRACE = timedelta(days=30)


def user_summary(user: User) -> UserSummary:
    return UserSummary(
        id=user.id,
        handle=user.handle,
        display_name=user.display_name,
        headline=user.headline,
        avatar=public_urls(user.avatar) if user.avatar else None,
        helper_score=user.helper_score,
    )


async def build_me(db: AsyncSession, user: User) -> MeOut:
    google_linked = bool(
        await db.scalar(
            select(
                exists().where(OAuthAccount.user_id == user.id, OAuthAccount.provider == "google")
            )
        )
    )
    return MeOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        handle=user.handle,
        display_name=user.display_name,
        headline=user.headline,
        bio=user.bio,
        profession=user.profession,
        location=user.location,
        frustrated_status=user.frustrated_status,
        links=user.links,
        avatar=public_urls(user.avatar) if user.avatar else None,
        cover=public_urls(user.cover) if user.cover else None,
        role=user.role,
        status=user.status,
        suspended_until=user.suspended_until,
        onboarded=user.onboarded,
        has_password=user.password_hash is not None,
        google_linked=google_linked,
        helper_score=user.helper_score,
        follower_count=user.follower_count,
        following_count=user.following_count,
        deletion_scheduled_at=user.deletion_scheduled_at,
        created_at=user.created_at,
    )


# --- Settings ----------------------------------------------------------------------------------


def settings_out(row: UserSettings | None) -> SettingsOut:
    return SettingsOut(
        privacy=PrivacySettings.model_validate(row.privacy if row else {}),
        notifications=NotificationSettings.model_validate(row.notifications if row else {}),
        content=ContentSettings.model_validate(row.content if row else {}),
    )


async def load_settings(db: AsyncSession, user_id: uuid.UUID) -> SettingsOut:
    return settings_out(await db.get(UserSettings, user_id))


async def load_settings_many(
    db: AsyncSession, user_ids: set[uuid.UUID]
) -> dict[uuid.UUID, SettingsOut]:
    rows = (await db.scalars(select(UserSettings).where(UserSettings.user_id.in_(user_ids)))).all()
    found = {r.user_id: settings_out(r) for r in rows}
    return {uid: found.get(uid) or settings_out(None) for uid in user_ids}


async def update_settings(db: AsyncSession, user: User, patch: SettingsPatchIn) -> SettingsOut:
    row = await db.get(UserSettings, user.id)
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
    if patch.privacy is not None:
        row.privacy = patch.privacy.model_dump(mode="json")
    if patch.notifications is not None:
        row.notifications = patch.notifications.model_dump(mode="json")
    if patch.content is not None:
        row.content = patch.content.model_dump(mode="json")
    await db.commit()
    from social_service import invalidate_viewer_ctx

    await invalidate_viewer_ctx(user.id)
    return settings_out(row)


# --- Profile -----------------------------------------------------------------------------------


async def get_visible_user(db: AsyncSession, handle: str, viewer: User | None) -> User:
    user = await db.scalar(select(User).where(User.handle == handle.lower()))
    if user is None or user.status in (UserStatus.banned, UserStatus.deleted):
        raise not_found("User")
    if (
        viewer is not None
        and viewer.id != user.id
        and await db.scalar(
            select(exists().where(Block.blocker_id == user.id, Block.blocked_id == viewer.id))
        )
    ):
        raise not_found("User")
    return user


async def get_profile(db: AsyncSession, handle: str, viewer: User | None) -> ProfileOut:
    user = await get_visible_user(db, handle, viewer)
    public = and_(
        Post.author_id == user.id,
        Post.is_anonymous.is_(False),
        Post.moderation_state == ModerationState.published,
        Post.deleted_at.is_(None),
    )
    counts = (
        await db.execute(
            select(
                func.count().filter(public),
                func.count().filter(and_(public, Post.status == PostStatus.solved)),
            )
            .select_from(Post)
            .where(Post.author_id == user.id)
        )
    ).one()
    badges = (
        await db.scalars(
            select(UserBadge.badge)
            .where(UserBadge.user_id == user.id)
            .order_by(UserBadge.awarded_at)
        )
    ).all()
    relations = (False, False, False, False)
    if viewer is not None and viewer.id != user.id:
        relations = tuple(
            (
                await db.execute(
                    select(
                        exists().where(
                            Follow.follower_id == viewer.id, Follow.followee_id == user.id
                        ),
                        exists().where(
                            Follow.follower_id == user.id, Follow.followee_id == viewer.id
                        ),
                        exists().where(Block.blocker_id == viewer.id, Block.blocked_id == user.id),
                        exists().where(Mute.muter_id == viewer.id, Mute.muted_id == user.id),
                    )
                )
            ).one()
        )
    privacy = (await load_settings(db, user.id)).privacy
    is_me = viewer is not None and viewer.id == user.id
    return ProfileOut(
        id=user.id,
        handle=user.handle,
        display_name=user.display_name,
        headline=user.headline,
        bio=user.bio,
        profession=None if privacy.hide_profession and not is_me else user.profession,
        location=None if privacy.hide_location and not is_me else user.location,
        frustrated_status=user.frustrated_status,
        links=user.links,
        avatar=public_urls(user.avatar) if user.avatar else None,
        cover=public_urls(user.cover) if user.cover else None,
        helper_score=user.helper_score,
        follower_count=user.follower_count,
        following_count=user.following_count,
        post_count=counts[0],
        solved_count=counts[1],
        badges=list(badges),
        joined_at=user.created_at,
        is_me=is_me,
        is_following=relations[0],
        follows_you=relations[1],
        is_blocked=relations[2],
        is_muted=relations[3],
    )


async def _image_variants(
    db: AsyncSession, user: User, media_id: uuid.UUID, purpose: MediaPurpose
) -> dict[str, str]:
    media = await db.get(Media, media_id)
    if media is None or media.owner_id != user.id or media.purpose != purpose:
        raise not_found("Media")
    if media.state != MediaState.ready:
        raise bad_request("media_not_ready", "Image is still processing or was rejected")
    return dict(media.variants)


async def update_profile(db: AsyncSession, user: User, data: ProfileUpdateIn) -> User:
    if data.handle is not None and data.handle != user.handle:
        if user.handle_changed_at and utcnow() - user.handle_changed_at < HANDLE_CHANGE_COOLDOWN:
            raise AppError(400, "handle_cooldown", "You can change your handle once every 30 days")
        if await db.scalar(select(exists().where(User.handle == data.handle))):
            raise conflict("handle_taken", "That handle is taken")
        user.handle = data.handle
        user.handle_changed_at = utcnow()
    for field in ("display_name", "headline", "bio", "profession", "location", "frustrated_status"):
        value = getattr(data, field)
        if value is not None:
            setattr(user, field, value)
    if data.links is not None:
        user.links = [str(link) for link in data.links]
    if data.remove_avatar:
        user.avatar = None
    elif data.avatar_media_id:
        user.avatar = await _image_variants(db, user, data.avatar_media_id, MediaPurpose.avatar)
    if data.remove_cover:
        user.cover = None
    elif data.cover_media_id:
        user.cover = await _image_variants(db, user, data.cover_media_id, MediaPurpose.cover)
    from auth_service import commit_or_conflict

    await commit_or_conflict(db)
    return user


async def complete_onboarding(db: AsyncSession, user: User, data: OnboardingIn) -> User:
    if user.onboarded:
        raise bad_request("already_onboarded", "Onboarding is already complete")
    if data.handle != user.handle and await db.scalar(
        select(exists().where(User.handle == data.handle))
    ):
        raise conflict("handle_taken", "That handle is taken")
    user.handle = data.handle
    user.display_name = data.display_name
    user.headline = data.headline
    user.onboarded = True
    from auth_service import commit_or_conflict

    await commit_or_conflict(db)
    return user


# --- Account lifecycle -------------------------------------------------------------------------


async def set_author_hidden(db: AsyncSession, user_id: uuid.UUID, hidden: bool) -> None:
    """Hide/show all of a user's content (ban, pending deletion). Caller commits."""
    from sqlalchemy import update as sa_update

    await db.execute(
        sa_update(Post)
        .where(Post.author_id == user_id, Post.author_hidden.is_not(hidden))
        .values(author_hidden=hidden)
    )
    await db.execute(
        sa_update(Comment)
        .where(Comment.author_id == user_id, Comment.author_hidden.is_not(hidden))
        .values(author_hidden=hidden)
    )


async def schedule_deletion(db: AsyncSession, user: User) -> None:
    from auth_service import revoke_all_sessions

    await set_author_hidden(db, user.id, True)
    user.status = UserStatus.deleted
    user.deletion_scheduled_at = utcnow() + DELETION_GRACE
    await revoke_all_sessions(db, user.id)
    await db.commit()


async def export_data(db: AsyncSession, user: User) -> dict[str, Any]:
    posts = (
        await db.scalars(select(Post).where(Post.author_id == user.id).order_by(Post.created_at))
    ).all()
    comments = (
        await db.scalars(
            select(Comment).where(Comment.author_id == user.id).order_by(Comment.created_at)
        )
    ).all()
    reactions = (await db.scalars(select(Reaction).where(Reaction.user_id == user.id))).all()
    following = (
        await db.scalars(
            select(User.handle)
            .join(Follow, Follow.followee_id == User.id)
            .where(Follow.follower_id == user.id)
        )
    ).all()
    me = await build_me(db, user)
    return {
        "exported_at": utcnow().isoformat(),
        "profile": me.model_dump(mode="json"),
        "settings": (await load_settings(db, user.id)).model_dump(mode="json"),
        "posts": [
            {
                "id": str(p.id),
                "title": p.title,
                "body": p.body,
                "category": p.category,
                "tags": p.tags,
                "anonymous": p.is_anonymous,
                "status": p.status,
                "moderation_state": p.moderation_state,
                "created_at": p.created_at.isoformat(),
                "deleted": p.deleted_at is not None,
            }
            for p in posts
        ],
        "comments": [
            {
                "id": str(c.id),
                "post_id": str(c.post_id),
                "body": c.body,
                "flair": c.flair,
                "created_at": c.created_at.isoformat(),
                "deleted": c.deleted_at is not None,
            }
            for c in comments
        ],
        "reactions": [{"post_id": str(r.post_id), "kind": r.kind} for r in reactions],
        "following": list(following),
    }


async def purge_due_accounts(limit: int = 100) -> int:
    """Cron: anonymise accounts whose 30-day deletion grace period has passed."""
    from sqlalchemy import delete as sa_delete
    from sqlalchemy import update as sa_update

    from database import SessionLocal
    from models import AuthSession, Mute, TopicFollow
    from tasks import enqueue

    async with SessionLocal() as db:
        due = (
            await db.scalars(
                select(User)
                .where(
                    User.status == UserStatus.deleted,
                    User.deletion_scheduled_at.is_not(None),
                    User.deletion_scheduled_at <= utcnow(),
                )
                .limit(limit)
            )
        ).all()
        for user in due:
            post_ids = (
                await db.scalars(
                    select(Post.id).where(Post.author_id == user.id, Post.deleted_at.is_(None))
                )
            ).all()
            now = utcnow()
            await db.execute(
                sa_update(Post)
                .where(Post.author_id == user.id, Post.deleted_at.is_(None))
                .values(deleted_at=now)
            )
            await db.execute(
                sa_update(Comment)
                .where(Comment.author_id == user.id, Comment.deleted_at.is_(None))
                .values(deleted_at=now)
            )
            # Keep other users' denormalised follower/following counters correct.
            await db.execute(
                sa_update(User)
                .where(User.id.in_(select(Follow.followee_id).where(Follow.follower_id == user.id)))
                .values(follower_count=func.greatest(User.follower_count - 1, 0))
            )
            await db.execute(
                sa_update(User)
                .where(User.id.in_(select(Follow.follower_id).where(Follow.followee_id == user.id)))
                .values(following_count=func.greatest(User.following_count - 1, 0))
            )
            for model, column in (
                (OAuthAccount, OAuthAccount.user_id),
                (AuthSession, AuthSession.user_id),
                (Follow, Follow.follower_id),
                (Follow, Follow.followee_id),
                (Block, Block.blocker_id),
                (Mute, Mute.muter_id),
                (TopicFollow, TopicFollow.user_id),
                (UserSettings, UserSettings.user_id),
            ):
                await db.execute(sa_delete(model).where(column == user.id))
            user.email = f"deleted+{user.id}@invalid.toxic-express"
            user.handle = f"deleted_{user.id.hex[:20]}"
            user.display_name = "Deleted user"
            user.password_hash = None
            user.headline = user.bio = user.profession = user.location = ""
            user.frustrated_status = ""
            user.links = []
            user.avatar = user.cover = None
            user.follower_count = user.following_count = 0
            user.deletion_scheduled_at = None
            await db.commit()
            for post_id in post_ids:
                await enqueue("delete_post_media", str(post_id))
        return len(due)
