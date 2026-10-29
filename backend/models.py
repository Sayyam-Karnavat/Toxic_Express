"""SQLAlchemy ORM models. All relationships use lazy="raise" so N+1 queries fail loudly."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from utils import uuid7

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def _enum(enum_cls: type[StrEnum], name: str) -> SAEnum:
    return SAEnum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=24,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid7)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


# --- Enums -------------------------------------------------------------------------------------


class Role(StrEnum):
    user = "user"
    mod = "mod"
    admin = "admin"


class UserStatus(StrEnum):
    active = "active"
    suspended = "suspended"
    banned = "banned"
    deleted = "deleted"


class Category(StrEnum):
    work = "work"
    tech = "tech"
    money = "money"
    relationships = "relationships"
    health = "health"
    customer_service = "customer_service"
    commute = "commute"
    life = "life"


class PostStatus(StrEnum):
    open = "open"
    seeking_advice = "seeking_advice"
    solved = "solved"


class ModerationState(StrEnum):
    pending = "pending"  # waiting for an automated check (e.g. moderation API was unavailable)
    pending_media = "pending_media"  # text passed, attached media still processing
    published = "published"
    in_review = "in_review"  # flagged, visible to the author only until a moderator decides
    removed = "removed"  # removed by a moderator
    rejected = "rejected"  # blocked automatically


class ReactionKind(StrEnum):
    same = "same"  # "Same here"
    hug = "hug"  # "Hugs"
    rage = "rage"  # "Rage with you"
    lol = "lol"


class CommentFlair(StrEnum):
    advice = "advice"
    support = "support"
    story = "story"


class MediaKind(StrEnum):
    image = "image"
    video = "video"


class MediaPurpose(StrEnum):
    post = "post"
    avatar = "avatar"
    cover = "cover"


class MediaState(StrEnum):
    uploading = "uploading"
    processing = "processing"
    ready = "ready"
    rejected = "rejected"
    deleted = "deleted"


class ReportReason(StrEnum):
    harassment = "harassment"
    hate = "hate"
    threat = "threat"
    doxxing = "doxxing"
    self_harm = "self_harm"
    sexual = "sexual"
    spam = "spam"
    other = "other"


class EntityType(StrEnum):
    post = "post"
    comment = "comment"
    user = "user"


class ReportStatus(StrEnum):
    open = "open"
    actioned = "actioned"
    dismissed = "dismissed"


class AppealStatus(StrEnum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"


# --- Users & auth ------------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_hash: Mapped[str | None] = mapped_column(String(255))
    handle: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    handle_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    display_name: Mapped[str] = mapped_column(String(50), nullable=False)
    headline: Mapped[str] = mapped_column(String(120), default="", server_default="")
    bio: Mapped[str] = mapped_column(String(300), default="", server_default="")
    profession: Mapped[str] = mapped_column(String(80), default="", server_default="")
    location: Mapped[str] = mapped_column(String(80), default="", server_default="")
    frustrated_status: Mapped[str] = mapped_column(String(100), default="", server_default="")
    links: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    avatar: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    cover: Mapped[dict[str, str] | None] = mapped_column(JSONB)
    helper_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    follower_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    following_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    role: Mapped[Role] = mapped_column(
        _enum(Role, "role"), default=Role.user, server_default="user"
    )
    status: Mapped[UserStatus] = mapped_column(
        _enum(UserStatus, "user_status"), default=UserStatus.active, server_default="active"
    )
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    onboarded: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))
    deletion_scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    settings: Mapped["UserSettings"] = relationship(back_populates="user", lazy="raise")

    __table_args__ = (
        CheckConstraint("handle ~ '^[a-z0-9_]{3,30}$'", name="handle_format"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        Index(
            "ix_users_handle_trgm",
            "handle",
            postgresql_using="gin",
            postgresql_ops={"handle": "gin_trgm_ops"},
        ),
        Index(
            "ix_users_display_name_trgm",
            "display_name",
            postgresql_using="gin",
            postgresql_ops={"display_name": "gin_trgm_ops"},
        ),
        Index(
            "ix_users_deletion_due",
            "deletion_scheduled_at",
            postgresql_where=text("deletion_scheduled_at IS NOT NULL"),
        ),
    )


class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    privacy: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    notifications: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    updated_at: Mapped[datetime] = _updated()

    user: Mapped[User] = relationship(back_populates="settings", lazy="raise")


class AuthSession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_token_hash: Mapped[str | None] = mapped_column(String(64))
    rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(255), default="", server_default="")
    ip: Mapped[str] = mapped_column(String(45), default="", server_default="")
    created_at: Mapped[datetime] = _created()
    last_used_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_oauth_accounts_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_oauth_accounts_user_provider"),
    )


# --- Content -----------------------------------------------------------------------------------

_PUBLISHED = text("moderation_state = 'published' AND deleted_at IS NULL")


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[uuid.UUID] = _pk()
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Category] = mapped_column(_enum(Category, "category"), nullable=False)
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(String(30)), default=list, server_default="{}", nullable=False
    )
    frustration_level: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[PostStatus] = mapped_column(
        _enum(PostStatus, "post_status"), default=PostStatus.open, server_default="open"
    )
    moderation_state: Mapped[ModerationState] = mapped_column(
        _enum(ModerationState, "moderation_state"), nullable=False
    )
    moderation_reason: Mapped[str | None] = mapped_column(String(200))
    moderation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    crisis_flag: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    content_warning: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    pinned_comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="SET NULL", use_alter=True)
    )
    solved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    same_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    hug_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rage_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    lol_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    comment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    report_weight: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    # True while the author is banned or pending deletion: hidden everywhere without losing state.
    author_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    link_preview: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(body, '')), 'B')",
            persisted=True,
        ),
        deferred=True,
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    author: Mapped[User] = relationship(lazy="raise", foreign_keys=[author_id])
    media: Mapped[list["Media"]] = relationship(
        lazy="raise",
        primaryjoin="and_(Media.post_id == Post.id, Media.state != 'deleted')",
        order_by="Media.position",
        viewonly=True,
    )

    __table_args__ = (
        CheckConstraint("frustration_level BETWEEN 1 AND 5", name="frustration_range"),
        CheckConstraint("cardinality(tags) <= 5", name="max_tags"),
        Index(
            "ix_posts_latest", text("created_at DESC"), text("id DESC"), postgresql_where=_PUBLISHED
        ),
        Index("ix_posts_author_latest", "author_id", text("created_at DESC"), text("id DESC")),
        Index(
            "ix_posts_category_latest",
            "category",
            text("created_at DESC"),
            text("id DESC"),
            postgresql_where=_PUBLISHED,
        ),
        Index(
            "ix_posts_solved",
            text("solved_at DESC"),
            text("id DESC"),
            postgresql_where=text(
                "status = 'solved' AND moderation_state = 'published' AND deleted_at IS NULL"
            ),
        ),
        Index("ix_posts_tags", "tags", postgresql_using="gin"),
        Index("ix_posts_search", "search_tsv", postgresql_using="gin"),
        Index(
            "ix_posts_mod_queue",
            "moderation_state",
            "created_at",
            postgresql_where=text("moderation_state IN ('pending', 'in_review')"),
        ),
    )


class Media(Base):
    __tablename__ = "media"

    id: Mapped[uuid.UUID] = _pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="SET NULL"), index=True
    )
    purpose: Mapped[MediaPurpose] = mapped_column(_enum(MediaPurpose, "media_purpose"))
    kind: Mapped[MediaKind] = mapped_column(_enum(MediaKind, "media_kind"))
    mime: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    position: Mapped[int] = mapped_column(SmallInteger, default=0, server_default="0")
    state: Mapped[MediaState] = mapped_column(
        _enum(MediaState, "media_state"), default=MediaState.uploading
    )
    variants: Mapped[dict[str, str]] = mapped_column(JSONB, default=dict, server_default="{}")
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    moderation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    reject_reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    __table_args__ = (
        Index(
            "ix_media_stale_uploads",
            "created_at",
            postgresql_where=text("state IN ('uploading', 'processing')"),
        ),
    )


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[uuid.UUID] = _pk()
    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True, nullable=False
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE")
    )  # indexed by ix_comments_replies
    body: Mapped[str] = mapped_column(Text, nullable=False)
    flair: Mapped[CommentFlair] = mapped_column(_enum(CommentFlair, "comment_flair"))
    # True when the post's anonymous author comments on their own post ("OP").
    is_anonymous: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    helpful_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reply_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    moderation_state: Mapped[ModerationState] = mapped_column(
        _enum(ModerationState, "moderation_state"), nullable=False
    )
    moderation: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    report_weight: Mapped[float] = mapped_column(Float, default=0, server_default="0")
    author_hidden: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=text("false")
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()

    author: Mapped[User] = relationship(lazy="raise")

    __table_args__ = (
        Index(
            "ix_comments_post_top",
            "post_id",
            "created_at",
            "id",
            postgresql_where=text("parent_id IS NULL"),
        ),
        Index(
            "ix_comments_replies",
            "parent_id",
            "created_at",
            "id",
            postgresql_where=text("parent_id IS NOT NULL"),
        ),
        Index(
            "ix_comments_mod_queue",
            "moderation_state",
            "created_at",
            postgresql_where=text("moderation_state IN ('pending', 'in_review')"),
        ),
    )


class Reaction(Base):
    __tablename__ = "reactions"

    post_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    kind: Mapped[ReactionKind] = mapped_column(_enum(ReactionKind, "reaction_kind"))
    created_at: Mapped[datetime] = _created()


class CommentVote(Base):
    __tablename__ = "comment_votes"

    comment_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), primary_key=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = _created()


class Tag(Base):
    __tablename__ = "tags"

    name: Mapped[str] = mapped_column(String(30), primary_key=True)
    post_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    __table_args__ = (Index("ix_tags_prefix", "name", postgresql_ops={"name": "text_pattern_ops"}),)


# --- Social graph ------------------------------------------------------------------------------


class Follow(Base):
    __tablename__ = "follows"

    follower_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    followee_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        CheckConstraint("follower_id <> followee_id", name="no_self_follow"),
        Index("ix_follows_followee", "followee_id", text("created_at DESC")),
        Index("ix_follows_follower", "follower_id", text("created_at DESC")),
    )


class TopicFollow(Base):
    """A user following a category ("category:work") or a tag ("tag:burnout")."""

    __tablename__ = "topic_follows"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    topic: Mapped[str] = mapped_column(String(40), primary_key=True)
    created_at: Mapped[datetime] = _created()


class Block(Base):
    __tablename__ = "blocks"

    blocker_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    blocked_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = _created()


class Mute(Base):
    __tablename__ = "mutes"

    muter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    muted_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = _created()


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    post_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("posts.id", ondelete="CASCADE"), index=True
    )
    comment_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")
    # Repeated events with the same key bump one notification instead of creating many.
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    actor: Mapped[User | None] = relationship(lazy="raise", foreign_keys=[actor_id])

    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe"),
        Index("ix_notifications_user_latest", "user_id", text("created_at DESC"), text("id DESC")),
        Index("ix_notifications_unread", "user_id", postgresql_where=text("read_at IS NULL")),
    )


# --- Trust & safety ----------------------------------------------------------------------------


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = _pk()
    reporter_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reason: Mapped[ReportReason] = mapped_column(_enum(ReportReason, "report_reason"))
    note: Mapped[str] = mapped_column(String(500), default="", server_default="")
    weight: Mapped[float] = mapped_column(Float, default=1.0, server_default="1")
    status: Mapped[ReportStatus] = mapped_column(
        _enum(ReportStatus, "report_status"), default=ReportStatus.open, server_default="open"
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()

    __table_args__ = (
        UniqueConstraint("reporter_id", "entity_type", "entity_id", name="uq_reports_once"),
        Index("ix_reports_entity", "entity_type", "entity_id"),
        Index("ix_reports_open", "created_at", postgresql_where=text("status = 'open'")),
    )


class ModerationAction(Base):
    __tablename__ = "moderation_actions"

    id: Mapped[uuid.UUID] = _pk()
    moderator_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )  # NULL = automated system action
    target_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    entity_type: Mapped[EntityType] = mapped_column(_enum(EntityType, "entity_type"))
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), default="", server_default="")
    created_at: Mapped[datetime] = _created()

    __table_args__ = (Index("ix_moderation_actions_latest", text("created_at DESC")),)


class Strike(Base):
    __tablename__ = "strikes"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    action_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("moderation_actions.id", ondelete="SET NULL")
    )
    reason: Mapped[str] = mapped_column(String(500), default="", server_default="")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = _created()


class Appeal(Base):
    __tablename__ = "appeals"

    id: Mapped[uuid.UUID] = _pk()
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    action_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("moderation_actions.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    message: Mapped[str] = mapped_column(String(1000), nullable=False)
    status: Mapped[AppealStatus] = mapped_column(
        _enum(AppealStatus, "appeal_status"), default=AppealStatus.open, server_default="open"
    )
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class UserBadge(Base):
    __tablename__ = "user_badges"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    badge: Mapped[str] = mapped_column(String(32), primary_key=True)
    awarded_at: Mapped[datetime] = _created()
