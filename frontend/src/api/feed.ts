import { useInfiniteQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAuth } from "@/store/auth";
import type { Category, PostPage } from "@/types";

import { keys } from "./keys";

export type FeedSort = "following" | "latest" | "trending" | "solved";

export interface FeedParams {
  sort: FeedSort;
  category?: Category | undefined;
  tag?: string | undefined;
}

export function useFeed(params: FeedParams, enabled = true) {
  const authed = useAuth((s) => s.status === "authenticated");
  return useInfiniteQuery({
    queryKey: keys.feed({ ...params }),
    // The following feed needs a session; never fire it before auth has been restored.
    enabled: enabled && (params.sort !== "following" || authed),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      params.sort === "following"
        ? api<PostPage>("/feed/following", { query: { cursor: pageParam }, signal })
        : api<PostPage>("/feed", {
            query: { sort: params.sort, category: params.category, tag: params.tag, cursor: pageParam },
            signal,
          }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useUserPosts(handle: string) {
  return useInfiniteQuery({
    queryKey: keys.userPosts(handle),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api<PostPage>(`/users/${encodeURIComponent(handle)}/posts`, { query: { cursor: pageParam }, signal }),
    getNextPageParam: (last) => last.next_cursor,
  });
}
