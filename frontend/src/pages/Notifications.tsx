import { useQueryClient } from "@tanstack/react-query";
import { Award, CheckCircle2, Heart, MessageCircle, ShieldAlert, ThumbsUp, UserPlus } from "lucide-react";
import { useEffect } from "react";
import { Link } from "react-router-dom";

import { keys } from "@/api/keys";
import { useMarkRead, useNotifications } from "@/api/notifications";
import { InfiniteLoader } from "@/components/InfiniteLoader";
import { AnonAvatar, Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/empty-state";
import { PageSpinner } from "@/components/ui/spinner";
import { errorMessage } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import type { Notification } from "@/types";

const ICONS: Record<string, typeof Heart> = {
  reaction: Heart, comment: MessageCircle, reply: MessageCircle, follow: UserPlus, solved: CheckCircle2,
  helpful: ThumbsUp, badge: Award, moderation: ShieldAlert, media_rejected: ShieldAlert, appeal: ShieldAlert,
};
const REACTION: Record<string, string> = { same: "said \"same here\" to", hug: "sent hugs on", rage: "is raging with you on", lol: "laughed at" };

function describe(n: Notification): { text: string; href: string } {
  const who = n.actor?.display_name ?? "Someone";
  const title = typeof n.data.post_title === "string" ? `"${n.data.post_title}"` : "your rant";
  const post = n.post_id ? `/p/${n.post_id}` : "/";
  switch (n.type) {
    case "reaction": return { text: `${who} ${REACTION[String(n.data.kind)] ?? "reacted to"} ${title}`, href: post };
    case "comment": return { text: `${who} responded to ${title}`, href: post };
    case "reply": return { text: `${who} replied to your comment on ${title}`, href: post };
    case "follow": return { text: `${who} started following you`, href: n.actor ? `/u/${n.actor.handle}` : "/" };
    case "solved": return { text: `Your comment helped solve ${title}. +10 Helper Score`, href: post };
    case "helpful": return { text: `${who} found your comment helpful`, href: post };
    case "badge": return { text: `You earned a badge: ${String(n.data.description ?? n.data.badge)}`, href: "/settings/profile" };
    case "moderation": return { text: `A moderator took action on your content (${String(n.data.action)}). You can appeal.`, href: "/settings/moderation" };
    case "media_rejected": return { text: `Media on ${title} didn't pass our checks`, href: post };
    case "appeal": return { text: `Your appeal was ${n.data.accepted ? "accepted" : "reviewed and declined"}`, href: "/settings/moderation" };
    default: return { text: "New activity", href: post };
  }
}

export default function NotificationsPage() {
  const qc = useQueryClient();
  const query = useNotifications();
  const markRead = useMarkRead();
  const items = query.data?.pages.flatMap((p) => p.items) ?? [];

  useEffect(() => {
    void qc.invalidateQueries({ queryKey: keys.unread });
  }, [qc, items.length]);

  if (query.isLoading) return <PageSpinner />;
  if (query.isError) return <ErrorState message={errorMessage(query.error)} onRetry={() => void query.refetch()} />;
  return (
    <div className="space-y-md">
      <div className="flex items-center justify-between">
        <h1 className="font-display text-heading-sm font-bold uppercase">Notifications</h1>
        {items.some((n) => !n.read) && (
          <Button size="sm" variant="ghost" loading={markRead.isPending} onClick={() => markRead.mutate({ all: true }, { onSuccess: () => void qc.invalidateQueries({ queryKey: keys.unread }) })}>
            Mark all read
          </Button>
        )}
      </div>
      {!items.length ? (
        <EmptyState title="All quiet">Reactions, replies and follows will show up here.</EmptyState>
      ) : (
        <ul className="space-y-xs">
          {items.map((n) => {
            const { text, href } = describe(n);
            const Icon = ICONS[n.type] ?? Heart;
            return (
              <li key={n.id}>
                <Link
                  to={href}
                  onClick={() => !n.read && markRead.mutate({ ids: [n.id] })}
                  className={cn("flex items-center gap-sm rounded-md p-md hover:bg-surface-raised", n.read ? "bg-canvas" : "bg-surface-indigo")}
                >
                  {n.actor ? <Avatar src={n.actor.avatar?.["96"]} name={n.actor.display_name} /> : <AnonAvatar />}
                  <span className="min-w-0 flex-1">
                    <span className="block text-body">{text}</span>
                    <span className="text-link-sm text-ink-faint">{timeAgo(n.created_at)}</span>
                  </span>
                  <Icon className="size-5 shrink-0 text-link-cyan" aria-hidden />
                  {!n.read && <span className="size-2 shrink-0 rounded-full bg-green" aria-label="Unread" />}
                </Link>
              </li>
            );
          })}
        </ul>
      )}
      <InfiniteLoader hasNextPage={!!query.hasNextPage} isFetchingNextPage={query.isFetchingNextPage} fetchNextPage={query.fetchNextPage} />
    </div>
  );
}
