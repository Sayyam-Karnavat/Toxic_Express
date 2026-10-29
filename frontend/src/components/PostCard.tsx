import { CheckCircle2, MessageCircle, MoreHorizontal, Pencil, Trash2, Flag, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { useDeletePost } from "@/api/posts";
import { useSettings } from "@/api/users";
import { errorMessage } from "@/lib/api";
import { cn, compactNumber, timeAgo } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import { isPublicPost, type Post } from "@/types";

import { CategoryChip, TagChip } from "./CategoryChip";
import { Composer } from "./Composer";
import { CrisisBanner } from "./CrisisBanner";
import { FrustrationMeter } from "./FrustrationMeter";
import { Markdown } from "./Markdown";
import { PostMedia } from "./PostMedia";
import { ReactionBar } from "./ReactionBar";
import { ReportDialog } from "./ReportDialog";
import { AnonAvatar, Avatar } from "./ui/avatar";
import { Badge } from "./ui/badge";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "./ui/dropdown";

const STATE_NOTE: Record<string, string> = {
  pending: "Checking your rant. It will appear publicly once it passes moderation.",
  pending_media: "Processing your media. Your rant goes live when it's done.",
  in_review: "A moderator is reviewing this rant. Only you can see it for now.",
  removed: "This rant was removed by a moderator.",
  rejected: "This rant didn't pass moderation.",
};

export function PostAuthor({ post }: { post: Post }) {
  if (!isPublicPost(post)) {
    return (
      <div className="flex items-center gap-sm">
        <AnonAvatar />
        <div>
          <p className="font-medium">Anonymous ranter{post.is_own && " (you)"}</p>
          <p className="text-link-sm text-ink-faint">{timeAgo(post.created_at)}</p>
        </div>
      </div>
    );
  }
  const a = post.author;
  return (
    <Link to={`/u/${a.handle}`} className="flex min-w-0 items-center gap-sm">
      <Avatar src={a.avatar?.["96"]} name={a.display_name} />
      <div className="min-w-0">
        <p className="truncate font-medium hover:underline">{a.display_name}</p>
        <p className="truncate text-link-sm text-ink-faint">
          @{a.handle}
          {a.headline && <> · {a.headline}</>} · {timeAgo(post.created_at)}
        </p>
      </div>
    </Link>
  );
}

export function PostCard({ post, detail = false }: { post: Post; detail?: boolean }) {
  const authed = useAuth((s) => s.status === "authenticated");
  const { data: settings } = useSettings();
  const navigate = useNavigate();
  const del = useDeletePost();
  const [reporting, setReporting] = useState(false);
  const [editing, setEditing] = useState(false);
  const [showWarned, setShowWarned] = useState(!post.content_warning);
  const blur = settings?.content.blur_sensitive_media ?? true;
  const href = `/p/${post.id}`;

  return (
    <article className="rounded-lg bg-surface-indigo p-xl" aria-labelledby={`post-${post.id}-title`}>
      <header className="flex items-start justify-between gap-sm">
        <PostAuthor post={post} />
        <div className="flex shrink-0 items-center gap-xs">
          {post.status === "solved" && (
            <Badge variant="green">
              <CheckCircle2 className="size-3.5" aria-hidden /> Solved
            </Badge>
          )}
          {authed && (
            <DropdownMenu>
              <DropdownTrigger className="rounded-full p-xs text-ink-soft hover:bg-surface-raised" aria-label="Rant options">
                <MoreHorizontal className="size-5" />
              </DropdownTrigger>
              <DropdownContent>
                {post.can_edit && (
                  <DropdownItem onSelect={() => setEditing(true)}>
                    <Pencil className="size-4" /> Edit
                  </DropdownItem>
                )}
                {post.is_own ? (
                  <DropdownItem
                    danger
                    onSelect={() =>
                      window.confirm("Delete this rant? This can't be undone.") &&
                      del.mutate(post.id, {
                        onSuccess: () => {
                          toast.success("Rant deleted");
                          if (detail) navigate("/");
                        },
                        onError: (e) => toast.error(errorMessage(e)),
                      })
                    }
                  >
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
      </header>

      {post.is_own && STATE_NOTE[post.moderation_state] && (
        <p className="mt-md flex items-center gap-xs rounded-sm bg-canvas px-sm py-xs text-link-sm text-ink-soft">
          <ShieldAlert className="size-4 shrink-0" aria-hidden /> {STATE_NOTE[post.moderation_state]}
        </p>
      )}

      <div className="mt-md flex flex-wrap items-center gap-sm">
        <CategoryChip category={post.category} />
        <FrustrationMeter level={post.frustration_level} />
        {post.status === "seeking_advice" && <Badge variant="outline">Seeking advice</Badge>}
      </div>

      <h3 id={`post-${post.id}-title`} className={cn("mt-sm font-display font-bold", detail ? "text-heading-sm" : "text-link-lg")}>
        {detail ? post.title : <Link to={href} className="hover:underline">{post.title}</Link>}
      </h3>

      {showWarned ? (
        <>
          <Markdown className={cn("mt-xs text-body text-ink-soft", !detail && "line-clamp-6")}>{post.body}</Markdown>
          <PostMedia media={post.media} sensitive={blur && post.content_warning} />
          {post.link_preview && <LinkPreview preview={post.link_preview as unknown as Preview} />}
        </>
      ) : (
        <button
          type="button"
          onClick={() => setShowWarned(true)}
          className="mt-sm w-full rounded-sm border border-dashed border-indigo-line p-md text-left text-link-sm text-ink-soft"
        >
          Content warning: this rant may be upsetting. Show it anyway.
        </button>
      )}

      {post.tags.length > 0 && (
        <div className="mt-sm flex flex-wrap gap-sm">
          {post.tags.map((t) => (
            <TagChip key={t} tag={t} />
          ))}
        </div>
      )}

      {post.show_crisis_resources && <CrisisBanner compact={!detail} />}

      <footer className="mt-md flex flex-wrap items-center justify-between gap-sm">
        <ReactionBar post={post} />
        {!detail && (
          <Link to={href} className="inline-flex min-h-9 items-center gap-xxs text-link-sm text-ink-soft hover:text-ink">
            <MessageCircle className="size-4" aria-hidden /> {compactNumber(post.comment_count)}
            <span className="sr-only">comments</span>
          </Link>
        )}
      </footer>

      {reporting && <ReportDialog open={reporting} onOpenChange={setReporting} entityType="post" entityId={post.id} />}
      {editing && <Composer open={editing} onOpenChange={setEditing} editing={post} />}
    </article>
  );
}

interface Preview {
  url: string;
  domain: string;
  title: string;
  description: string;
}

function LinkPreview({ preview }: { preview: Preview }) {
  return (
    <a
      href={preview.url}
      target="_blank"
      rel="noopener noreferrer nofollow ugc"
      className="mt-md block rounded-md border border-indigo-line bg-canvas p-md hover:border-primary"
    >
      <p className="text-link-sm text-ink-faint">{preview.domain}</p>
      <p className="font-medium">{preview.title}</p>
      {preview.description && <p className="line-clamp-2 text-link-sm text-ink-soft">{preview.description}</p>}
    </a>
  );
}

export function PostSkeleton() {
  return (
    <div className="animate-pulse rounded-lg bg-surface-indigo p-xl" aria-hidden>
      <div className="flex items-center gap-sm">
        <div className="size-10 rounded-full bg-indigo-line" />
        <div className="h-3 w-40 rounded bg-indigo-line" />
      </div>
      <div className="mt-md h-4 w-3/4 rounded bg-indigo-line" />
      <div className="mt-sm h-3 w-full rounded bg-indigo-line" />
      <div className="mt-xs h-3 w-5/6 rounded bg-indigo-line" />
    </div>
  );
}
