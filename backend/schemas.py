"""Pydantic request/response models.

Anonymity is structural: AnonPostOut / AnonCommentOut have no author fields at all, so an
anonymous author can never be serialised by accident.
"""

import re
import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    HttpUrl,
    field_validator,
)

from models import (
    AppealStatus,
    Category,
    CommentFlair,
    EntityType,
    MediaKind,
    MediaPurpose,
    MediaState,
    ModerationState,
    PostStatus,
    ReactionKind,
    ReportReason,
    ReportStatus,
    Role,
    UserStatus,
)
from utils import clean_text

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,30}$")
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,28}[a-z0-9]$")
RESERVED_HANDLES = frozenset(
    {
        "admin",
        "administrator",
        "api",
        "app",
        "auth",
        "help",
        "me",
        "mod",
        "mods",
        "moderator",
        "root",
        "settings",
        "signup",
        "login",
        "logout",
        "support",
        "system",
        "toxic_express",
        "toxicexpress",
        "official",
        "staff",
        "anonymous",
        "anon",
        "deleted",
        "null",
        "undefined",
    }
)


class In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def _handle(value: str) -> str:
    value = value.lower()
    if not HANDLE_RE.match(value):
        raise ValueError("Handle must be 3-30 characters: lowercase letters, digits, underscore")
    if value in RESERVED_HANDLES or value.startswith("deleted_"):
        raise ValueError("This handle is reserved")
    return value


def _single_line(value: str) -> str:
    return clean_text(value, multiline=False)


def _multi_line(value: str) -> str:
    return clean_text(value, multiline=True)


Handle = Annotated[str, AfterValidator(_handle)]
Line = Annotated[str, AfterValidator(_single_line)]
Paragraph = Annotated[str, AfterValidator(_multi_line)]


def _normalise_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for raw in tags:
        tag = raw.strip().lower().lstrip("#").replace(" ", "-")
        if not TAG_RE.match(tag):
            raise ValueError(f"Invalid tag '{raw}': 2-30 chars, letters, digits and hyphens")
        if tag not in out:
            out.append(tag)
    if len(out) > 5:
        raise ValueError("At most 5 tags")
    return out


# --- Auth --------------------------------------------------------------------------------------


class SignupIn(In):
    email: EmailStr
    password: str = Field(min_length=10, max_length=128)
    handle: Handle
    display_name: Line = Field(min_length=1, max_length=50)


class LoginIn(In):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenIn(In):
    token: str = Field(min_length=10, max_length=200)


class EmailIn(In):
    email: EmailStr


class ResetPasswordIn(In):
    token: str = Field(min_length=10, max_length=200)
    password: str = Field(min_length=10, max_length=128)


class SetPasswordIn(In):
    password: str = Field(min_length=10, max_length=128)
    current_password: str | None = Field(default=None, max_length=128)


class OnboardingIn(In):
    handle: Handle
    display_name: Line = Field(min_length=1, max_length=50)
    headline: Line = Field(default="", max_length=120)


class AuthUrlOut(BaseModel):
    url: str


# --- Users -------------------------------------------------------------------------------------


class UserSummary(Out):
    id: uuid.UUID
    handle: str
    display_name: str
    headline: str
    avatar: dict[str, str] | None = None
    helper_score: int


class MeOut(Out):
    id: uuid.UUID
    email: str
    email_verified: bool
    handle: str
    display_name: str
    headline: str
    bio: str
    profession: str
    location: str
    frustrated_status: str
    links: list[str]
    avatar: dict[str, str] | None
    cover: dict[str, str] | None
    role: Role
    status: UserStatus
    suspended_until: datetime | None
    onboarded: bool
    has_password: bool
    google_linked: bool
    helper_score: int
    follower_count: int
    following_count: int
    deletion_scheduled_at: datetime | None
    created_at: datetime


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int
    user: MeOut


class ProfileOut(BaseModel):
    id: uuid.UUID
    handle: str
    display_name: str
    headline: str
    bio: str
    profession: str | None
    location: str | None
    frustrated_status: str
    links: list[str]
    avatar: dict[str, str] | None
    cover: dict[str, str] | None
    helper_score: int
    follower_count: int
    following_count: int
    post_count: int
    solved_count: int
    badges: list[str]
    joined_at: datetime
    is_me: bool
    is_following: bool
    follows_you: bool
    is_blocked: bool
    is_muted: bool


class ProfileUpdateIn(In):
    handle: Handle | None = None
    display_name: Line | None = Field(default=None, min_length=1, max_length=50)
    headline: Line | None = Field(default=None, max_length=120)
    bio: Paragraph | None = Field(default=None, max_length=300)
    profession: Line | None = Field(default=None, max_length=80)
    location: Line | None = Field(default=None, max_length=80)
    frustrated_status: Line | None = Field(default=None, max_length=100)
    links: list[HttpUrl] | None = Field(default=None, max_length=3)
    avatar_media_id: uuid.UUID | None = None
    cover_media_id: uuid.UUID | None = None
    remove_avatar: bool = False
    remove_cover: bool = False

    @field_validator("links")
    @classmethod
    def _https_only(cls, links: list[HttpUrl] | None) -> list[HttpUrl] | None:
        if links and any(link.scheme not in ("http", "https") for link in links):
            raise ValueError("Links must be http(s) URLs")
        return links


class PrivacySettings(In):
    default_anonymous: bool = False
    who_can_comment: Literal["everyone", "followers", "none"] = "everyone"
    hide_profession: bool = False
    hide_location: bool = False
    searchable: bool = True


class NotificationSettings(In):
    reactions: bool = True
    comments: bool = True
    replies: bool = True
    follows: bool = True
    solved: bool = True
    helpful: bool = True
    email_digest: Literal["never", "weekly"] = "never"


class ContentSettings(In):
    muted_words: list[Annotated[str, Field(min_length=2, max_length=40)]] = Field(
        default_factory=list, max_length=50
    )
    muted_categories: list[Category] = Field(default_factory=list)
    blur_sensitive_media: bool = True
    hide_content_warning_posts: bool = False
    preferred_categories: list[Category] = Field(default_factory=list)

    @field_validator("muted_words")
    @classmethod
    def _dedupe_words(cls, words: list[str]) -> list[str]:
        return list(dict.fromkeys(w.strip().lower() for w in words if w.strip()))


class SettingsOut(BaseModel):
    privacy: PrivacySettings
    notifications: NotificationSettings
    content: ContentSettings


class SettingsPatchIn(In):
    privacy: PrivacySettings | None = None
    notifications: NotificationSettings | None = None
    content: ContentSettings | None = None


class SessionOut(Out):
    id: uuid.UUID
    user_agent: str
    ip: str
    created_at: datetime
    last_used_at: datetime
    current: bool = False


class EmailChangeIn(In):
    email: EmailStr
    password: str | None = Field(default=None, max_length=128)


class DeleteAccountIn(In):
    password: str | None = Field(default=None, max_length=128)
    confirm: Literal["DELETE"]


# --- Media -------------------------------------------------------------------------------------


class UploadUrlIn(In):
    kind: MediaKind
    purpose: MediaPurpose = MediaPurpose.post
    mime: str = Field(max_length=64)
    size_bytes: int = Field(gt=0)


class UploadUrlOut(BaseModel):
    media_id: uuid.UUID
    upload_url: str
    method: Literal["PUT"] = "PUT"
    headers: dict[str, str]
    expires_in: int


class MediaOut(BaseModel):
    id: uuid.UUID
    kind: MediaKind
    purpose: MediaPurpose
    state: MediaState
    urls: dict[str, str]
    width: int | None
    height: int | None
    duration_seconds: float | None
    reject_reason: str | None = None


# --- Posts -------------------------------------------------------------------------------------


class PostCreateIn(In):
    title: Line = Field(min_length=3, max_length=120)
    body: Paragraph = Field(min_length=1, max_length=5000)
    category: Category
    tags: list[str] = Field(default_factory=list, max_length=10)
    frustration_level: int = Field(ge=1, le=5)
    is_anonymous: bool | None = None  # None -> the user's default from privacy settings
    content_warning: bool = False
    status: Literal[PostStatus.open, PostStatus.seeking_advice] = PostStatus.open
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str]) -> list[str]:
        return _normalise_tags(v)


class PostUpdateIn(In):
    title: Line | None = Field(default=None, min_length=3, max_length=120)
    body: Paragraph | None = Field(default=None, min_length=1, max_length=5000)
    category: Category | None = None
    tags: list[str] | None = Field(default=None, max_length=10)
    frustration_level: int | None = Field(default=None, ge=1, le=5)
    content_warning: bool | None = None
    status: Literal[PostStatus.open, PostStatus.seeking_advice] | None = None

    @field_validator("tags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else _normalise_tags(v)


class ReactionIn(In):
    kind: ReactionKind


class SolveIn(In):
    comment_id: uuid.UUID | None = None


class ReactionCounts(BaseModel):
    same: int
    hug: int
    rage: int
    lol: int
    total: int


class _PostBase(BaseModel):
    id: uuid.UUID
    title: str
    body: str
    category: Category
    tags: list[str]
    frustration_level: int
    status: PostStatus
    moderation_state: ModerationState
    content_warning: bool
    show_crisis_resources: bool
    media: list[MediaOut]
    reactions: ReactionCounts
    my_reaction: ReactionKind | None
    comment_count: int
    pinned_comment_id: uuid.UUID | None
    solved_at: datetime | None
    link_preview: dict[str, Any] | None
    created_at: datetime
    edited_at: datetime | None
    is_own: bool
    can_edit: bool


class PostOut(_PostBase):
    is_anonymous: Literal[False] = False
    author: UserSummary


class AnonPostOut(_PostBase):
    is_anonymous: Literal[True] = True


AnyPostOut = Annotated[PostOut | AnonPostOut, Field(discriminator="is_anonymous")]


class PostPage(BaseModel):
    items: list[AnyPostOut]
    next_cursor: str | None


# --- Comments ----------------------------------------------------------------------------------


class CommentCreateIn(In):
    body: Paragraph = Field(min_length=1, max_length=2000)
    flair: CommentFlair = CommentFlair.support
    parent_id: uuid.UUID | None = None


class CommentUpdateIn(In):
    body: Paragraph = Field(min_length=1, max_length=2000)


class _CommentBase(BaseModel):
    id: uuid.UUID
    post_id: uuid.UUID
    parent_id: uuid.UUID | None
    body: str
    flair: CommentFlair
    helpful_count: int
    my_helpful: bool
    reply_count: int
    is_op: bool
    is_pinned: bool
    is_own: bool
    deleted: bool
    moderation_state: ModerationState
    created_at: datetime
    edited_at: datetime | None
    replies: list["AnyCommentOut"] = Field(default_factory=list)


class CommentOut(_CommentBase):
    is_anonymous: Literal[False] = False
    author: UserSummary | None  # None only for deleted comments


class AnonCommentOut(_CommentBase):
    is_anonymous: Literal[True] = True


AnyCommentOut = Annotated[CommentOut | AnonCommentOut, Field(discriminator="is_anonymous")]


class CommentPage(BaseModel):
    items: list[AnyCommentOut]
    next_cursor: str | None


# --- Social & notifications --------------------------------------------------------------------


class UserPage(BaseModel):
    items: list[UserSummary]
    next_cursor: str | None


class TopicIn(In):
    topic: str = Field(pattern=r"^(category|tag):[a-z0-9_-]{2,30}$")


class TopicsOut(BaseModel):
    topics: list[str]


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: str
    actor: UserSummary | None
    post_id: uuid.UUID | None
    comment_id: uuid.UUID | None
    data: dict[str, Any]
    read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    next_cursor: str | None


class UnreadCountOut(BaseModel):
    unread: int


class MarkReadIn(In):
    ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    all: bool = False


# --- Search ------------------------------------------------------------------------------------


class TagOut(Out):
    name: str
    post_count: int


class SearchOut(BaseModel):
    posts: list[AnyPostOut]
    users: list[UserSummary]
    tags: list[TagOut]
    next_cursor: str | None


# --- Reports, moderation, appeals --------------------------------------------------------------


class ReportIn(In):
    entity_type: EntityType
    entity_id: uuid.UUID
    reason: ReportReason
    note: Line = Field(default="", max_length=500)


class ModActionIn(In):
    entity_type: EntityType
    entity_id: uuid.UUID
    action: Literal[
        "approve", "remove", "restore", "dismiss_reports", "strike", "suspend", "ban", "unban"
    ]
    reason: Line = Field(default="", max_length=500)
    suspend_days: int = Field(default=7, ge=1, le=365)


class QueueItemOut(BaseModel):
    entity_type: EntityType
    entity_id: uuid.UUID
    moderation_state: ModerationState | None
    moderation_reason: str | None
    title: str | None
    body: str
    is_anonymous: bool
    author: UserSummary
    report_count: int
    report_weight: float
    report_reasons: list[str]
    flags: dict[str, Any] | None
    created_at: datetime


class QueueOut(BaseModel):
    items: list[QueueItemOut]
    next_cursor: str | None


class ModActionOut(Out):
    id: uuid.UUID
    moderator_id: uuid.UUID | None
    target_user_id: uuid.UUID | None
    entity_type: EntityType
    entity_id: uuid.UUID
    action: str
    reason: str
    created_at: datetime


class AuditPage(BaseModel):
    items: list[ModActionOut]
    next_cursor: str | None


class AppealIn(In):
    action_id: uuid.UUID
    message: Paragraph = Field(min_length=10, max_length=1000)


class AppealResolveIn(In):
    accept: bool
    note: Line = Field(default="", max_length=500)


class AppealOut(Out):
    id: uuid.UUID
    user_id: uuid.UUID
    action_id: uuid.UUID
    message: str
    status: AppealStatus
    created_at: datetime
    resolved_at: datetime | None


class AppealPage(BaseModel):
    items: list[AppealOut]
    next_cursor: str | None


class ReportOut(Out):
    id: uuid.UUID
    entity_type: EntityType
    entity_id: uuid.UUID
    reason: ReportReason
    status: ReportStatus
    created_at: datetime


class OkOut(BaseModel):
    ok: bool = True
