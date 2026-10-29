import { Flame, HandHeart, Laugh, Users } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { useReaction } from "@/api/posts";
import { errorMessage } from "@/lib/api";
import { cn, compactNumber } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import type { Post, ReactionKind } from "@/types";

const REACTIONS: { kind: ReactionKind; label: string; Icon: typeof Users }[] = [
  { kind: "same", label: "Same here", Icon: Users },
  { kind: "hug", label: "Hugs", Icon: HandHeart },
  { kind: "rage", label: "Rage with you", Icon: Flame },
  { kind: "lol", label: "Lol", Icon: Laugh },
];

export function ReactionBar({ post }: { post: Post }) {
  const authed = useAuth((s) => s.status === "authenticated");
  const navigate = useNavigate();
  const mutation = useReaction(post.id);
  const [popped, setPopped] = useState<ReactionKind | null>(null);
  const disabled = post.moderation_state !== "published";

  const toggle = (kind: ReactionKind) => {
    if (!authed) return navigate(`/login?next=/p/${post.id}`);
    setPopped(kind);
    mutation.mutate(post.my_reaction === kind ? null : kind, {
      onError: (err) => toast.error(errorMessage(err)),
    });
  };

  return (
    <div className="flex flex-wrap gap-xs" role="group" aria-label="Reactions">
      {REACTIONS.map(({ kind, label, Icon }) => {
        const active = post.my_reaction === kind;
        const count = post.reactions[kind];
        return (
          <button
            key={kind}
            type="button"
            disabled={disabled || mutation.isPending}
            aria-pressed={active}
            onClick={() => toggle(kind)}
            onAnimationEnd={() => setPopped(null)}
            className={cn(
              "inline-flex min-h-9 items-center gap-xxs rounded-pill px-sm text-link-sm transition-colors disabled:opacity-50",
              active ? "bg-primary text-on-primary" : "bg-canvas text-ink-soft hover:bg-surface-raised hover:text-ink",
              popped === kind && "reaction-pop",
            )}
          >
            <Icon className="size-4" aria-hidden />
            <span>{label}</span>
            {count > 0 && <span className="font-semibold">{compactNumber(count)}</span>}
          </button>
        );
      })}
    </div>
  );
}
