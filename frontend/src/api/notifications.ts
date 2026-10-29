import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAuth } from "@/store/auth";
import type { NotificationPage } from "@/types";

import { keys } from "./keys";

export function useUnreadCount() {
  const authed = useAuth((s) => s.status === "authenticated");
  return useQuery({
    queryKey: keys.unread,
    queryFn: () => api<{ unread: number }>("/notifications/unread-count"),
    enabled: authed,
    refetchInterval: 30_000,
    refetchIntervalInBackground: false,
  });
}

export function useNotifications() {
  return useInfiniteQuery({
    queryKey: keys.notifications,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) => api<NotificationPage>("/notifications", { query: { cursor: pageParam } }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useMarkRead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { ids?: string[]; all?: boolean }) => api("/notifications/read", { method: "POST", body }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: keys.notifications }),
  });
}
