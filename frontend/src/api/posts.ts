import { type InfiniteData, type QueryClient, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Post, PostCreate, PostPage, PostUpdate, ReactionKind } from "@/types";

import { keys } from "./keys";

/** Write an updated post into its detail cache and into every cached feed page. */
export function patchPost(qc: QueryClient, post: Post) {
  qc.setQueryData(keys.post(post.id), post);
  qc.setQueriesData<InfiniteData<PostPage>>({ queryKey: keys.feedRoot }, (data) =>
    data
      ? {
          ...data,
          pages: data.pages.map((page) => ({
            ...page,
            items: page.items.map((p) => (p.id === post.id ? post : p)),
          })),
        }
      : data,
  );
}

function removePost(qc: QueryClient, id: string) {
  qc.removeQueries({ queryKey: keys.post(id) });
  qc.setQueriesData<InfiniteData<PostPage>>({ queryKey: keys.feedRoot }, (data) =>
    data
      ? { ...data, pages: data.pages.map((page) => ({ ...page, items: page.items.filter((p) => p.id !== id) })) }
      : data,
  );
}

export function usePost(id: string) {
  return useQuery({ queryKey: keys.post(id), queryFn: () => api<Post>(`/posts/${id}`) });
}

export function useCreatePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PostCreate) => api<Post>("/posts", { method: "POST", body }),
    onSuccess: (post) => {
      qc.setQueryData(keys.post(post.id), post);
      void qc.invalidateQueries({ queryKey: keys.feedRoot });
    },
  });
}

export function useUpdatePost(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: PostUpdate) => api<Post>(`/posts/${id}`, { method: "PATCH", body }),
    onSuccess: (post) => patchPost(qc, post),
  });
}

export function useDeletePost() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api(`/posts/${id}`, { method: "DELETE" }),
    onSuccess: (_, id) => removePost(qc, id),
  });
}

export function useReaction(postId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (kind: ReactionKind | null) =>
      kind
        ? api<Post>(`/posts/${postId}/reaction`, { method: "PUT", body: { kind } })
        : api<Post>(`/posts/${postId}/reaction`, { method: "DELETE" }),
    onSuccess: (post) => patchPost(qc, post),
  });
}

export function useSolve(postId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (commentId: string | null | "unsolve") =>
      commentId === "unsolve"
        ? api<Post>(`/posts/${postId}/solve`, { method: "DELETE" })
        : api<Post>(`/posts/${postId}/solve`, { method: "POST", body: { comment_id: commentId } }),
    onSuccess: (post) => {
      patchPost(qc, post);
      void qc.invalidateQueries({ queryKey: keys.comments(postId) });
    },
  });
}
