import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { SearchResult } from "@/types";

import { keys } from "./keys";

export function useSearch(q: string, type: "all" | "posts" | "users" | "tags") {
  return useQuery({
    queryKey: keys.search(q, type),
    queryFn: ({ signal }) => api<SearchResult>("/search", { query: { q, type }, signal }),
    enabled: q.trim().length >= 2,
    staleTime: 30_000,
  });
}
