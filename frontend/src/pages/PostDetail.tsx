import { ArrowLeft, CheckCircle2 } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { usePost, useSolve } from "@/api/posts";
import { CommentThread } from "@/components/CommentThread";
import { PostCard } from "@/components/PostCard";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/empty-state";
import { PageSpinner } from "@/components/ui/spinner";
import { ApiError, errorMessage } from "@/lib/api";

export default function PostDetail() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const query = usePost(id);
  const solve = useSolve(id);

  if (query.isLoading) return <PageSpinner />;
  if (query.error instanceof ApiError && query.error.status === 404) {
    return (
      <EmptyState title="Rant not found" action={<Button asChild><Link to="/">Back to the feed</Link></Button>}>
        It may have been deleted or is waiting for moderation.
      </EmptyState>
    );
  }
  if (query.isError || !query.data) return <ErrorState message={errorMessage(query.error)} onRetry={() => void query.refetch()} />;
  const post = query.data;

  return (
    <div>
      <button onClick={() => (window.history.length > 1 ? navigate(-1) : navigate("/"))} className="mb-md inline-flex items-center gap-xs text-link-sm text-ink-soft hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden /> Back
      </button>
      <PostCard post={post} detail />
      {post.is_own && post.moderation_state === "published" && (
        <div className="mt-md flex flex-wrap items-center justify-between gap-sm rounded-lg border border-indigo-line p-md">
          <p className="text-link-sm text-ink-soft">
            {post.status === "solved"
              ? "Marked as solved. Nice one."
              : "Sorted it out? Pin the comment that helped (from its menu), or just mark it solved."}
          </p>
          {post.status === "solved" ? (
            <Button size="sm" variant="ghost" loading={solve.isPending} onClick={() => solve.mutate("unsolve")}>Reopen</Button>
          ) : (
            <Button size="sm" variant="green" loading={solve.isPending} onClick={() => solve.mutate(null, { onSuccess: () => toast.success("Marked as solved"), onError: (e) => toast.error(errorMessage(e)) })}>
              <CheckCircle2 className="size-4" aria-hidden /> Mark solved
            </Button>
          )}
        </div>
      )}
      <CommentThread post={post} />
    </div>
  );
}
