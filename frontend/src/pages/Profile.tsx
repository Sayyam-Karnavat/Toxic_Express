import { Ban, Flag, MoreHorizontal, VolumeX } from "lucide-react";
import { useState } from "react";
import { Link, NavLink, useParams } from "react-router-dom";
import { toast } from "sonner";

import { useUserPosts } from "@/api/feed";
import { useMeta } from "@/api/meta";
import { useFollows, useProfile, useRelationship } from "@/api/users";
import { InfiniteLoader } from "@/components/InfiniteLoader";
import { PostCard, PostSkeleton } from "@/components/PostCard";
import { ReportDialog } from "@/components/ReportDialog";
import { UserRow } from "@/components/UserRow";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownContent, DropdownItem, DropdownMenu, DropdownTrigger } from "@/components/ui/dropdown";
import { EmptyState, ErrorState } from "@/components/ui/empty-state";
import { PageSpinner } from "@/components/ui/spinner";
import { ApiError, errorMessage } from "@/lib/api";
import { cn, compactNumber } from "@/lib/utils";
import { useAuth } from "@/store/auth";

const BADGE_LABEL: Record<string, string> = {
  problem_solver: "Problem Solver",
  survivor: "Survivor",
  good_listener: "Good Listener",
  helpful_hand: "Helpful Hand",
};

/** DESIGN.md `stat-card`: Blurple, big number. */
function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="rounded-lg bg-primary p-md text-center">
      <p className="font-display text-heading-sm font-bold">{compactNumber(value)}</p>
      <p className="text-link-sm">{label}</p>
    </div>
  );
}

export default function ProfilePage({ tab = "rants" }: { tab?: "rants" | "followers" | "following" }) {
  const { handle = "" } = useParams();
  const me = useAuth((s) => s.user);
  const { data: meta } = useMeta();
  const query = useProfile(handle);
  const rel = useRelationship(handle);
  const [reporting, setReporting] = useState(false);

  if (query.isLoading) return <PageSpinner />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return <EmptyState title="User not found">This account doesn't exist or isn't available.</EmptyState>;
  }
  if (query.isError || !query.data) return <ErrorState message={errorMessage(query.error)} onRetry={() => void query.refetch()} />;
  const p = query.data;
  const onError = (e: unknown) => toast.error(errorMessage(e));

  return (
    <div className="space-y-md">
      <section className="overflow-hidden rounded-lg bg-surface-indigo">
        <div className={cn("h-36 tablet:h-48", !p.cover && "mesh-bg")}>
          {p.cover && <img src={p.cover.large} alt="" className="size-full object-cover" />}
        </div>
        <div className="px-xl pb-xl">
          <div className="-mt-12 flex flex-wrap items-end justify-between gap-md">
            <Avatar src={p.avatar?.["400"]} name={p.display_name} size="lg" className="border-4 border-surface-indigo" />
            <div className="flex items-center gap-xs">
              {p.is_me ? (
                <Button asChild variant="ghost" size="sm"><Link to="/settings/profile">Edit profile</Link></Button>
              ) : me ? (
                <>
                  {p.is_following ? (
                    <Button variant="ghost" size="sm" loading={rel.unfollow.isPending} onClick={() => rel.unfollow.mutate(undefined, { onError })}>Following</Button>
                  ) : (
                    <Button size="sm" loading={rel.follow.isPending} onClick={() => rel.follow.mutate(undefined, { onError })} disabled={p.is_blocked}>
                      {p.follows_you ? "Follow back" : "Follow"}
                    </Button>
                  )}
                  <DropdownMenu>
                    <DropdownTrigger className="rounded-full p-xs hover:bg-surface-raised" aria-label="More options">
                      <MoreHorizontal className="size-5" />
                    </DropdownTrigger>
                    <DropdownContent>
                      {!p.is_muted && (
                        <DropdownItem onSelect={() => rel.mute.mutate(undefined, { onSuccess: () => toast("Muted. Their rants won't show in your feeds."), onError })}>
                          <VolumeX className="size-4" /> Mute
                        </DropdownItem>
                      )}
                      {!p.is_blocked && (
                        <DropdownItem danger onSelect={() => window.confirm(`Block @${p.handle}? You won't see each other.`) && rel.block.mutate(undefined, { onSuccess: () => toast("Blocked"), onError })}>
                          <Ban className="size-4" /> Block
                        </DropdownItem>
                      )}
                      <DropdownItem onSelect={() => setReporting(true)}>
                        <Flag className="size-4" /> Report
                      </DropdownItem>
                    </DropdownContent>
                  </DropdownMenu>
                </>
              ) : null}
            </div>
          </div>
          <h1 className="mt-sm font-display text-heading-sm font-bold">{p.display_name}</h1>
          <p className="text-link-sm text-ink-faint">
            @{p.handle}
            {p.follows_you && <Badge variant="dark" className="ml-xs py-0">Follows you</Badge>}
          </p>
          {p.headline && <p className="mt-xs text-body">{p.headline}</p>}
          {p.frustrated_status && (
            <p className="mt-xs text-link-sm text-ink-soft">
              <span className="text-magenta">●</span> Currently frustrated by: {p.frustrated_status}
            </p>
          )}
          {p.bio && <p className="mt-sm whitespace-pre-line text-body text-ink-soft">{p.bio}</p>}
          <p className="mt-sm text-link-sm text-ink-faint">
            {[p.profession, p.location].filter(Boolean).join(" · ")}
            {(p.profession || p.location) && " · "}Joined {new Date(p.joined_at).toLocaleDateString("en", { month: "long", year: "numeric" })}
          </p>
          {p.links.length > 0 && (
            <ul className="mt-xs flex flex-wrap gap-md text-link-sm">
              {p.links.map((l) => (
                <li key={l}>
                  <a href={l} target="_blank" rel="noopener noreferrer nofollow ugc" className="text-link-cyan hover:underline">
                    {new URL(l).hostname.replace(/^www\./, "")}
                  </a>
                </li>
              ))}
            </ul>
          )}
          {p.badges.length > 0 && (
            <div className="mt-md flex flex-wrap gap-xs">
              {p.badges.map((b) => (
                <Badge key={b} title={meta?.badges[b]}>{BADGE_LABEL[b] ?? b}</Badge>
              ))}
            </div>
          )}
          <div className="mt-md grid grid-cols-2 gap-sm tablet:grid-cols-4">
            <Stat value={p.helper_score} label="Helper Score" />
            <Stat value={p.post_count} label="Rants" />
            <Stat value={p.solved_count} label="Solved" />
            <Stat value={p.follower_count} label="Followers" />
          </div>
        </div>
      </section>

      <nav aria-label="Profile sections" className="flex gap-xxs rounded-lg bg-surface-indigo p-xxs">
        {[
          { to: `/u/${p.handle}`, label: "Rants" },
          { to: `/u/${p.handle}/followers`, label: `Followers · ${p.follower_count}` },
          { to: `/u/${p.handle}/following`, label: `Following · ${p.following_count}` },
        ].map((t) => (
          <NavLink key={t.to} to={t.to} end className={({ isActive }) => cn("min-h-10 rounded-md px-md py-xs text-link", isActive ? "bg-primary text-on-primary" : "text-ink-soft hover:text-ink")}>
            {t.label}
          </NavLink>
        ))}
      </nav>

      {tab === "rants" ? <UserRants handle={p.handle} isMe={p.is_me} /> : <FollowList handle={p.handle} direction={tab} />}
      {reporting && <ReportDialog open={reporting} onOpenChange={setReporting} entityType="user" entityId={p.id} />}
    </div>
  );
}

function UserRants({ handle, isMe }: { handle: string; isMe: boolean }) {
  const query = useUserPosts(handle);
  const posts = query.data?.pages.flatMap((p) => p.items) ?? [];
  if (query.isLoading) return <PostSkeleton />;
  if (!posts.length) {
    return <EmptyState title="No public rants yet">{isMe ? "Your anonymous rants only show here for you." : "Quiet one, huh."}</EmptyState>;
  }
  return (
    <div className="space-y-md">
      {posts.map((post) => <PostCard key={post.id} post={post} />)}
      <InfiniteLoader hasNextPage={!!query.hasNextPage} isFetchingNextPage={query.isFetchingNextPage} fetchNextPage={query.fetchNextPage} />
    </div>
  );
}

function FollowList({ handle, direction }: { handle: string; direction: "followers" | "following" }) {
  const query = useFollows(handle, direction);
  const users = query.data?.pages.flatMap((p) => p.items) ?? [];
  if (query.isLoading) return <PageSpinner />;
  if (!users.length) return <EmptyState title={direction === "followers" ? "No followers yet" : "Not following anyone yet"} />;
  return (
    <>
      <ul className="space-y-xs">{users.map((u) => <UserRow key={u.id} user={u} />)}</ul>
      <InfiniteLoader hasNextPage={!!query.hasNextPage} isFetchingNextPage={query.isFetchingNextPage} fetchNextPage={query.fetchNextPage} />
    </>
  );
}
