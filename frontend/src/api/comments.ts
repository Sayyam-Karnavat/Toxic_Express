import { type InfiniteData, useInfiniteQuery, useMutation, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Comment, CommentCreate, CommentPage } from "@/types";

import { keys } from "./keys";

export function useComments(postId: string) {
  return useInfiniteQuery({
    queryKey: keys.comments(postId),
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api<CommentPage>(`/posts/${postId}/comments`, { query: { cursor: pageParam }, signal }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

export function useReplies(commentId: string, enabled: boolean) {
  return useInfiniteQuery({
    queryKey: keys.replies(commentId),
    enabled,
    initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) =>
      api<CommentPage>(`/comments/${commentId}/replies`, { query: { cursor: pageParam }, signal }),
    getNextPageParam: (last) => last.next_cursor,
  });
}

function patchComment(data: InfiniteData<CommentPage> | undefined, comment: Comment) {
  if (!data) return data;
  const swap = (c: Comment): Comment =>
    c.id === comment.id ? { ...comment, replies: c.replies } : { ...c, replies: c.replies?.map(swap) ?? [] };
  return { ...data, pages: data.pages.map((p) => ({ ...p, items: p.items.map(swap) })) };
}

export function useCommentMutations(postId: string) {
  const qc = useQueryClient();
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: keys.comments(postId) });
    void qc.invalidateQueries({ queryKey: ["replies"] });
    void qc.invalidateQueries({ queryKey: keys.post(postId) });
  };
  const update = (comment: Comment) => {
    qc.setQueryData<InfiniteData<CommentPage>>(keys.comments(postId), (d) => patchComment(d, comment));
    qc.setQueriesData<InfiniteData<CommentPage>>({ queryKey: ["replies"] }, (d) => patchComment(d, comment));
  };
  return {
    create: useMutation({
      mutationFn: (body: CommentCreate) => api<Comment>(`/posts/${postId}/comments`, { method: "POST", body }),
      onSuccess: refresh,
    }),
    edit: useMutation({
      mutationFn: ({ id, body }: { id: string; body: string }) =>
        api<Comment>(`/comments/${id}`, { method: "PATCH", body: { body } }),
      onSuccess: update,
    }),
    remove: useMutation({
      mutationFn: (id: string) => api(`/comments/${id}`, { method: "DELETE" }),
      onSuccess: refresh,
    }),
    helpful: useMutation({
      mutationFn: ({ id, value }: { id: string; value: boolean }) =>
        api<Comment>(`/comments/${id}/helpful`, { method: value ? "PUT" : "DELETE" }),
      onSuccess: update,
    }),
  };
}
