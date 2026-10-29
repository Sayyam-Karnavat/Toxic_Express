import { Flame } from "lucide-react";
import { Link, NavLink, useOutletContext, useParams } from "react-router-dom";

import { type FeedSort, useFeed } from "@/api/feed";
import { useCategoryLabel } from "@/api/meta";
import { useTopicMutation, useTopics } from "@/api/users";
import { InfiniteLoader } from "@/components/InfiniteLoader";
import { PostCard, PostSkeleton } from "@/components/PostCard";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/empty-state";
import { errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import type { Category } from "@/types";

import Landing from "./Landing";

const TABS: { sort: FeedSort; label: string; to: string; auth?: boolean }[] = [
  { sort: "following", label: "Following", to: "/", auth: true },
  { sort: "latest", label: "Latest", to: "/latest" },
  { sort: "trending", label: "Trending", to: "/trending" },
  { sort: "solved", label: "Solved", to: "/solved" },
];

function FeedTabs() {
  const authed = useAuth((s) => s.status === "authenticated");
  return (
    <nav aria-label="Feed" className="flex gap-xxs overflow-x-auto rounded-lg bg-surface-indigo p-xxs">
      {TABS.filter((t) => authed || !t.auth).map((t) => (
        <NavLink
          key={t.sort}
          to={t.to}
          end
          className={({ isActive }) =>
            cn(
              "min-h-10 whitespace-nowrap rounded-md px-md py-xs text-link",
              isActive ? "bg-primary text-on-primary" : "text-ink-soft hover:text-ink",
            )
          }
        >
          {t.label}
        </NavLink>
      ))}
    </nav>
  );
}

function FollowTopic({ topic, label }: { topic: string; label: string }) {
  const authed = useAuth((s) => s.status === "authenticated");
  const { data } = useTopics();
  const mutation = useTopicMutation();
  if (!authed) return null;
  const following = data?.topics.includes(topic) ?? false;
  return (
    <Button
      size="sm"
      variant={following ? "ghost" : "primary"}
      loading={mutation.isPending}
      onClick={() => mutation.mutate({ topic, follow: !following })}
    >
      {following ? `Following ${label}` : `Follow ${label}`}
    </Button>
  );
}

export function FeedList({ sort, category, tag }: { sort: FeedSort; category?: Category; tag?: string }) {
  const query = useFeed({ sort, category, tag });
  const { compose } = useOutletContext<{ compose: () => void }>() ?? { compose: () => {} };
  const posts = query.data?.pages.flatMap((p) => p.items) ?? [];

  if (query.isLoading) {
    return (
      <div className="space-y-md">
        <PostSkeleton />
        <PostSkeleton />
        <PostSkeleton />
      </div>
    );
  }
  if (query.isError) return <ErrorState message={errorMessage(query.error)} onRetry={() => void query.refetch()} />;
  if (!posts.length) {
    return sort === "following" ? (
      <EmptyState
        title="Your feed is quiet"
        action={<Button variant="green" className="font-display uppercase" onClick={compose}>Scream it</Button>}
      >
        Follow people and categories to fill it up, browse <Link to="/trending" className="text-link-cyan underline">trending rants</Link>, or start one yourself.
      </EmptyState>
    ) : (
      <EmptyState title="Nothing here yet">Be the first to rant about it.</EmptyState>
    );
  }
  return (
    <div className="space-y-md">
      {sort === "trending" && !category && posts[0] && (
        <p className="flex items-center gap-xs text-link-sm text-ink-soft">
          <Flame className="size-4 text-magenta" aria-hidden /> Ranked by how many people relate, recently.
        </p>
      )}
      {posts.map((p) => (
        <PostCard key={p.id} post={p} />
      ))}
      <InfiniteLoader hasNextPage={!!query.hasNextPage} isFetchingNextPage={query.isFetchingNextPage} fetchNextPage={query.fetchNextPage} />
    </div>
  );
}

export function HomePage() {
  const status = useAuth((s) => s.status);
  if (status === "loading") return <PostSkeleton />;
  if (status === "anonymous") return <Landing />;
  return (
    <div className="space-y-md">
      <FeedTabs />
      <FeedList sort="following" />
    </div>
  );
}

export function SortedFeedPage({ sort }: { sort: Exclude<FeedSort, "following"> }) {
  return (
    <div className="space-y-md">
      <FeedTabs />
      <FeedList sort={sort} />
    </div>
  );
}

export function CategoryPage() {
  const { category = "" } = useParams();
  const label = useCategoryLabel();
  const cat = category as Category;
  return (
    <div className="space-y-md">
      <header className="flex flex-wrap items-center justify-between gap-md rounded-lg bg-surface-indigo p-xl">
        <h1 className="font-display text-heading-lg font-bold uppercase leading-none">{label(cat)}</h1>
        <FollowTopic topic={`category:${cat}`} label={label(cat)} />
      </header>
      <FeedList sort="latest" category={cat} />
    </div>
  );
}

export function TagPage() {
  const { tag = "" } = useParams();
  return (
    <div className="space-y-md">
      <header className="flex flex-wrap items-center justify-between gap-md rounded-lg bg-surface-indigo p-xl">
        <h1 className="font-display text-heading-lg font-bold leading-none">#{tag}</h1>
        <FollowTopic topic={`tag:${tag}`} label={`#${tag}`} />
      </header>
      <FeedList sort="latest" tag={tag} />
    </div>
  );
}
