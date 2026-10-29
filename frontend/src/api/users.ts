import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { useAuth } from "@/store/auth";
import type { Me, ModAction, Profile, SessionInfo, Settings, UserPage, UserSummary } from "@/types";

import { keys } from "./keys";

export function useProfile(handle: string) {
  return useQuery({
    queryKey: keys.profile(handle),
    queryFn: () => api<Profile>(`/users/${encodeURIComponent(handle)}`),
  });
}

export function useFollows(handle: string, direction: "followers" | "following") {
  return useInfiniteQuery({
    queryKey: keys.follows(handle, direction),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam }) =>
      api<UserPage>(`/users/${encodeURIComponent(handle)}/${direction}`, { query: { cursor: pageParam } }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useRelationship(handle: string) {
  const qc = useQueryClient();
  const done = () => {
    void qc.invalidateQueries({ queryKey: keys.profile(handle) });
    void qc.invalidateQueries({ queryKey: keys.feedRoot });
    void qc.invalidateQueries({ queryKey: keys.blocks });
    void qc.invalidateQueries({ queryKey: keys.mutes });
  };
  const path = `/users/${encodeURIComponent(handle)}`;
  return {
    follow: useMutation({ mutationFn: () => api(`${path}/follow`, { method: "POST" }), onSuccess: done }),
    unfollow: useMutation({ mutationFn: () => api(`${path}/follow`, { method: "DELETE" }), onSuccess: done }),
    block: useMutation({ mutationFn: () => api(`${path}/block`, { method: "POST" }), onSuccess: done }),
    mute: useMutation({ mutationFn: () => api(`${path}/mute`, { method: "POST" }), onSuccess: done }),
  };
}

export function useUpdateMe() {
  const setUser = useAuth((s) => s.setUser);
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, unknown>) => api<Me>("/me", { method: "PATCH", body }),
    onSuccess: (me) => {
      setUser(me);
      void qc.invalidateQueries({ queryKey: keys.profile(me.handle) });
    },
  });
}

export function useSettings() {
  const authed = useAuth((s) => s.status === "authenticated");
  return useQuery({
    queryKey: keys.settings,
    queryFn: () => api<Settings>("/me/settings"),
    enabled: authed,
    staleTime: 5 * 60_000,
  });
}

export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<Settings>) => api<Settings>("/me/settings", { method: "PATCH", body }),
    onSuccess: (s) => {
      qc.setQueryData(keys.settings, s);
      void qc.invalidateQueries({ queryKey: keys.feedRoot });
    },
  });
}

export function useSessions() {
  return useQuery({ queryKey: keys.sessions, queryFn: () => api<SessionInfo[]>("/me/sessions") });
}

export function useBlockedMuted(kind: "blocks" | "mutes") {
  return useQuery({
    queryKey: kind === "blocks" ? keys.blocks : keys.mutes,
    queryFn: () => api<UserSummary[]>(`/me/${kind}`),
  });
}

export function useTopics() {
  return useQuery({ queryKey: keys.topics, queryFn: () => api<{ topics: string[] }>("/me/topics") });
}

export function useTopicMutation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ topic, follow }: { topic: string; follow: boolean }) =>
      follow
        ? api<{ topics: string[] }>("/me/topics", { method: "POST", body: { topic } })
        : api<{ topics: string[] }>(`/me/topics/${encodeURIComponent(topic)}`, { method: "DELETE" }),
    onSuccess: (data) => {
      qc.setQueryData(keys.topics, data);
      void qc.invalidateQueries({ queryKey: keys.feed({ sort: "following" }) });
    },
  });
}

export function useMyModerationActions() {
  return useQuery({ queryKey: keys.myActions, queryFn: () => api<ModAction[]>("/me/moderation-actions") });
}

export async function refreshMe(): Promise<void> {
  const me = await api<Me>("/me");
  useAuth.getState().setUser(me);
}
