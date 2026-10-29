import type { components } from "./api";

type S = components["schemas"];

export type Me = S["MeOut"];
export type TokenOut = S["TokenOut"];
export type UserSummary = S["UserSummary"];
export type Profile = S["ProfileOut"];
export type PublicPost = S["PostOut"];
export type AnonPost = S["AnonPostOut"];
export type Post = PublicPost | AnonPost;
export type PostPage = S["PostPage"];
export type PostCreate = S["PostCreateIn"];
export type PostUpdate = S["PostUpdateIn"];
export type Comment = S["CommentOut"] | S["AnonCommentOut"];
export type CommentPage = S["CommentPage"];
export type CommentCreate = S["CommentCreateIn"];
export type Media = S["MediaOut"];
export type UploadTicket = S["UploadUrlOut"];
export type Settings = S["SettingsOut"];
export type PrivacySettings = S["PrivacySettings"];
export type NotificationSettings = S["NotificationSettings"];
export type ContentSettings = S["ContentSettings"];
export type SessionInfo = S["SessionOut"];
export type Notification = S["NotificationOut"];
export type NotificationPage = S["NotificationPage"];
export type SearchResult = S["SearchOut"];
export type UserPage = S["UserPage"];
export type QueueItem = S["QueueItemOut"];
export type ModAction = S["ModActionOut"];
export type Appeal = S["AppealOut"];
export type Category = S["PostCreateIn"]["category"];
export type ReactionKind = S["ReactionIn"]["kind"];
export type Flair = NonNullable<S["CommentCreateIn"]["flair"]>;
export type ReportReason = S["ReportIn"]["reason"];
export type EntityType = S["ReportIn"]["entity_type"];
export type ModActionKind = S["ModActionIn"]["action"];

export interface Meta {
  categories: { value: Category; label: string }[];
  reactions: { value: ReactionKind; label: string }[];
  flairs: Flair[];
  report_reasons: ReportReason[];
  badges: Record<string, string>;
  limits: {
    title: number;
    body: number;
    comment: number;
    tags: number;
    images: number;
    image_bytes: number;
    video_bytes: number;
    video_seconds: number;
    edit_window_minutes: number;
  };
  crisis_resources: { region: string; name: string; url: string; phone?: string }[];
}

export function isPublicPost(post: Post): post is PublicPost {
  return post.is_anonymous === false;
}
