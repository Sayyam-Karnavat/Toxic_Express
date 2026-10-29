import { CheckCircle2, Flag, MoreHorizontal, Pencil, Pin, ThumbsUp, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { useCommentMutations, useComments, useReplies } from "@/api/comments";
import { useSolve } from "@/api/posts";
import { errorMessage } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import type { Comment, Flair, Post } from "@/types";

import { InfiniteLoader } from "./InfiniteLoader";
import { Markdown } from "./Markdown";
import { ReportDialog } from "./ReportDialog";
import { AnonAvatar, Avatar } from "./ui/avatar";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "./ui/dropdown";
import { EmptyState, ErrorState } from "./ui/empty-state";
import { Textarea } from "./ui/input";
import { PageSpinner } from "./ui/spinner";

const FLAIRS: { value: Flair; label: string }[] = [
  { value: "support", label: "Support" },
  { value: "advice", label: "Advice" },
  { value: "story", label: "Same story" },
];

export function CommentForm({
  post,
  parentId,
  onDone,
  autoFocus,
}: {
  post: Post;
  parentId?: string;
  onDone?: () => void;
  autoFocus?: boolean;
}) {
  const { create } = useCommentMutations(post.id);
  const [body, setBody] = useState("");
  const [flair, setFlair] = useState<Flair>(post.status === "seeking_advice" ? "advice" : "support");

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!body.trim()) return;
    create.mutate(
      { body, flair, parent_id: parentId ?? null },
      {
        onSuccess: (c) => {
          setBody("");
          onDone?.();
          if (c.moderation_state !== "published") toast("Your comment is being checked before it appears.");
        },
        onError: (err) => toast.error(errorMessage(err)),
      },
    );
  };

  return (
    <form onSubmit={submit} className="space-y-sm">
      <label htmlFor={`comment-${parentId ?? "root"}`} className="sr-only">
        {parentId ? "Write a reply" : "Write a comment"}
      </label>
      <Textarea
        id={`comment-${parentId ?? "root"}`}
        value={body}
        maxLength={2000}
        autoFocus={autoFocus}
        onChange={(e) => setBody(e.target.value)}
        placeholder={parentId ? "Reply..." : "Relate, support, or offer a way out..."}
        className="min-h-20"
      />
      <div className="flex flex-wrap items-center justify-between gap-sm">
        <div role="radiogroup" aria-label="Comment type" className="flex gap-xs">
          {FLAIRS.map((f) => (
            <button
              key={f.value}
              type="button"
              role="radio"
              aria-checked={flair === f.value}
              onClick={() => setFlair(f.value)}
              className={cn(
                "min-h-9 rounded-pill px-sm text-link-sm",
                flair === f.value ? "bg-primary text-on-primary" : "bg-canvas text-ink-soft hover:text-ink",
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
        <Button type="submit" size="sm" loading={create.isPending} disabled={!body.trim()}>
          {parentId ? "Reply" : "Comment"}
        </Button>
      </div>
    </form>
  );
}

function CommentItem({ comment, post, depth = 0 }: { comment: Comment; post: Post; depth?: number }) {
  const authed = useAuth((s) => s.status === "authenticated");
  const { edit, remove, helpful } = useCommentMutations(post.id);
  const solve = useSolve(post.id);
  const [replying, setReplying] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(comment.body);
  const [reporting, setReporting] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const moreReplies = useReplies(comment.id, showAll);
  const replies = showAll ? moreReplies.data?.pages.flatMap((p) => p.items) ?? comment.replies : comment.replies;

  const author =
    comment.is_anonymous || !comment.author ? null : comment.author;

  return (
    <li className={cn("rounded-lg p-md", comment.is_pinned ? "border border-green bg-canvas" : depth === 0 && "bg-canvas")}>
      <div className="flex items-start justify-between gap-sm">
        <div className="flex min-w-0 items-center gap-sm">
          {comment.deleted ? (
            <AnonAvatar size="sm" />
          ) : author ? (
            <Link to={`/u/${author.handle}`}>
              <Avatar src={author.avatar?.["96"]} name={author.display_name} size="sm" />
            </Link>
          ) : (
            <AnonAvatar size="sm" />
          )}
          <p className="min-w-0 truncate text-link-sm">
            {comment.deleted ? (
              <span className="text-ink-faint">Deleted</span>
            ) : author ? (
              <Link to={`/u/${author.handle}`} className="font-medium hover:underline">
                {author.display_name}
              </Link>
            ) : (
              <span className="font-medium">Anonymous ranter</span>
            )}
            {comment.is_op && <Badge variant="primary" className="ml-xs py-0">OP</Badge>}
            <span className="text-ink-faint"> · {timeAgo(comment.created_at)}{comment.edited_at && " · edited"}</span>
          </p>
        </div>
        <div className="flex items-center gap-xs">
          {comment.is_pinned && (
            <Badge variant="green"><Pin className="size-3.5" aria-hidden /> Helped solve it</Badge>
          )}
          {!comment.deleted && <Badge variant="outline" className="capitalize">{comment.flair}</Badge>}
          {authed && !comment.deleted && (
            <DropdownMenu>
              <DropdownTrigger className="rounded-full p-xxs text-ink-soft hover:bg-surface-raised" aria-label="Comment options">
                <MoreHorizontal className="size-4" />
              </DropdownTrigger>
              <DropdownContent>
                {post.is_own && post.moderation_state === "published" && !comment.is_pinned && (
                  <DropdownItem onSelect={() => solve.mutate(comment.id, { onSuccess: () => toast.success("Marked as solved"), onError: (e) => toast.error(errorMessage(e)) })}>
                    <CheckCircle2 className="size-4" /> This solved it
                  </DropdownItem>
                )}
                {comment.is_own && (
                  <DropdownItem onSelect={() => setEditing(true)}>
                    <Pencil className="size-4" /> Edit
                  </DropdownItem>
                )}
                {comment.is_own ? (
                  <DropdownItem danger onSelect={() => window.confirm("Delete this comment?") && remove.mutate(comment.id)}>
                    <Trash2 className="size-4" /> Delete
                  </DropdownItem>
                ) : (
                  <DropdownItem onSelect={() => setReporting(true)}>
                    <Flag className="size-4" /> Report
                  </DropdownItem>
                )}
              </DropdownContent>
            </DropdownMenu>
          )}
        </div>
      </div>

      {editing ? (
        <form
          className="mt-sm space-y-sm"
          onSubmit={(e) => {
            e.preventDefault();
            edit.mutate({ id: comment.id, body: draft }, { onSuccess: () => setEditing(false), onError: (er) => toast.error(errorMessage(er)) });
          }}
        >
          <Textarea value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={2000} aria-label="Edit comment" />
          <div className="flex justify-end gap-xs">
            <Button type="button" size="sm" variant="ghost" onClick={() => setEditing(false)}>Cancel</Button>
            <Button type="submit" size="sm" loading={edit.isPending}>Save</Button>
          </div>
        </form>
      ) : (
        <Markdown className={cn("mt-sm text-body", comment.deleted && "italic text-ink-faint")}>{comment.body}</Markdown>
      )}

      {!comment.deleted && (
        <div className="mt-sm flex flex-wrap items-center gap-xs">
          <button
            type="button"
            disabled={!authed || comment.is_own || helpful.isPending}
            aria-pressed={comment.my_helpful}
            onClick={() => helpful.mutate({ id: comment.id, value: !comment.my_helpful }, { onError: (e) => toast.error(errorMessage(e)) })}
            className={cn(
              "inline-flex min-h-9 items-center gap-xxs rounded-pill px-sm text-link-sm disabled:opacity-60",
              comment.my_helpful ? "bg-primary text-on-primary" : "bg-surface-indigo text-ink-soft hover:text-ink",
            )}
          >
            <ThumbsUp className="size-4" aria-hidden /> Helpful{comment.helpful_count > 0 && ` · ${comment.helpful_count}`}
          </button>
          {authed && depth === 0 && post.moderation_state === "published" && (
            <button type="button" onClick={() => setReplying((v) => !v)} className="min-h-9 px-sm text-link-sm text-ink-soft hover:text-ink">
              Reply
            </button>
          )}
          {post.is_own && comment.is_pinned && (
            <button type="button" onClick={() => solve.mutate("unsolve")} className="min-h-9 px-sm text-link-sm text-ink-soft hover:text-ink">
              Unpin
            </button>
          )}
        </div>
      )}

      {replying && (
        <div className="mt-sm">
          <CommentForm post={post} parentId={comment.id} onDone={() => setReplying(false)} autoFocus />
        </div>
      )}

      {replies && replies.length > 0 && (
        <ul className="mt-sm space-y-xs border-l-2 border-indigo-line pl-md">
          {replies.map((r) => (
            <CommentItem key={r.id} comment={r} post={post} depth={1} />
          ))}
        </ul>
      )}
      {depth === 0 && comment.reply_count > (comment.replies?.length ?? 0) && !showAll && (
        <button type="button" onClick={() => setShowAll(true)} className="mt-xs pl-md text-link-sm text-link-cyan hover:underline">
          Show all {comment.reply_count} replies
        </button>
      )}
      {showAll && (
        <InfiniteLoader
          hasNextPage={!!moreReplies.hasNextPage}
          isFetchingNextPage={moreReplies.isFetchingNextPage}
          fetchNextPage={moreReplies.fetchNextPage}
        />
      )}
      {reporting && <ReportDialog open={reporting} onOpenChange={setReporting} entityType="comment" entityId={comment.id} />}
    </li>
  );
}

export function CommentThread({ post }: { post: Post }) {
  const authed = useAuth((s) => s.status === "authenticated");
  const query = useComments(post.id);
  const comments = query.data?.pages.flatMap((p) => p.items) ?? [];
  const pinned = comments.find((c) => c.is_pinned);

  return (
    <section aria-labelledby="comments-heading" className="mt-xl space-y-md">
      <h2 id="comments-heading" className="font-display text-heading-sm font-bold uppercase">
        Responses <span className="text-ink-faint">({post.comment_count})</span>
      </h2>
      {authed && post.moderation_state === "published" ? (
        <div className="rounded-lg bg-surface-indigo p-md">
          <CommentForm post={post} />
        </div>
      ) : !authed ? (
        <p className="text-body text-ink-soft">
          <Link to={`/login?next=/p/${post.id}`} className="text-link-cyan underline">Log in</Link> to respond.
        </p>
      ) : null}
      {query.isLoading ? (
        <PageSpinner />
      ) : query.isError ? (
        <ErrorState message={errorMessage(query.error)} onRetry={() => void query.refetch()} />
      ) : comments.length === 0 ? (
        <EmptyState title="No responses yet">Be the first to say "same" or offer a way out.</EmptyState>
      ) : (
        <ul className="space-y-sm">
          {pinned && <CommentItem key={`pinned-${pinned.id}`} comment={pinned} post={post} />}
          {comments.filter((c) => !c.is_pinned).map((c) => (
            <CommentItem key={c.id} comment={c} post={post} />
          ))}
        </ul>
      )}
      <InfiniteLoader hasNextPage={!!query.hasNextPage} isFetchingNextPage={query.isFetchingNextPage} fetchNextPage={query.fetchNextPage} />
    </section>
  );
}
