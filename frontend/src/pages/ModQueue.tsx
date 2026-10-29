import { useState } from "react";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { useAppeals, useAudit, useModAction, useModQueue, useResolveAppeal } from "@/api/admin";
import { Avatar } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState, ErrorState } from "@/components/ui/empty-state";
import { PageSpinner } from "@/components/ui/spinner";
import { errorMessage } from "@/lib/api";
import { cn, timeAgo } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import type { ModActionKind, QueueItem } from "@/types";

function QueueCard({ item }: { item: QueueItem }) {
  const act = useModAction();
  const isAdmin = useAuth((s) => s.user?.role === "admin");
  const [reason, setReason] = useState("");
  const run = (action: ModActionKind) =>
    act.mutate(
      { entity_type: item.entity_type, entity_id: item.entity_id, action, reason },
      { onSuccess: () => toast.success(`Done: ${action}`), onError: (e) => toast.error(errorMessage(e)) },
    );
  const content = item.entity_type !== "user";
  return (
    <li className="rounded-lg bg-surface-indigo p-xl">
      <div className="flex flex-wrap items-center gap-xs text-link-sm">
        <Badge variant="primary" className="capitalize">{item.entity_type}</Badge>
        {item.moderation_state && <Badge variant="outline">{item.moderation_state}</Badge>}
        {item.report_count > 0 && <Badge>{item.report_count} reports · weight {item.report_weight}</Badge>}
        {item.is_anonymous && <Badge variant="dark">Posted anonymously</Badge>}
        <span className="text-ink-faint">{timeAgo(item.created_at)}</span>
      </div>
      <div className="mt-sm flex items-center gap-xs text-link-sm">
        <Avatar src={item.author.avatar?.["96"]} name={item.author.display_name} size="sm" />
        <Link to={`/u/${item.author.handle}`} className="hover:underline">{item.author.display_name} (@{item.author.handle})</Link>
      </div>
      {item.title && <p className="mt-sm font-display text-link-lg font-bold">{item.title}</p>}
      <p className="mt-xs whitespace-pre-line text-body text-ink-soft">{item.body || "(no text)"}</p>
      {(item.report_reasons.length > 0 || item.moderation_reason) && (
        <p className="mt-sm text-link-sm text-ink-faint">
          Signals: {[...item.report_reasons, item.moderation_reason].filter(Boolean).join(", ")}
        </p>
      )}
      {item.entity_type === "post" && (
        <Link to={`/p/${item.entity_id}`} className="mt-xs inline-block text-link-sm text-link-cyan underline">Open rant</Link>
      )}
      <label htmlFor={`reason-${item.entity_id}`} className="sr-only">Reason</label>
      <input
        id={`reason-${item.entity_id}`}
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        placeholder="Reason (shown to the user)"
        className="mt-md h-10 w-full rounded-sm border border-indigo-line bg-canvas px-sm text-link-sm"
      />
      <div className="mt-sm flex flex-wrap gap-xs">
        {content && <Button size="sm" variant="green" loading={act.isPending} onClick={() => run("approve")}>Approve</Button>}
        {content && <Button size="sm" variant="danger" onClick={() => run("remove")}>Remove</Button>}
        <Button size="sm" variant="ghost" onClick={() => run("dismiss_reports")}>Dismiss reports</Button>
        <Button size="sm" variant="ghost" onClick={() => run("strike")}>Strike author</Button>
        <Button size="sm" variant="ghost" onClick={() => run("suspend")}>Suspend 7 days</Button>
        {isAdmin && <Button size="sm" variant="danger" onClick={() => window.confirm("Ban this account?") && run("ban")}>Ban</Button>}
      </div>
    </li>
  );
}

export default function ModQueuePage() {
  const [tab, setTab] = useState<"queue" | "appeals" | "audit">("queue");
  const queue = useModQueue();
  const appeals = useAppeals();
  const audit = useAudit();
  const resolve = useResolveAppeal();

  return (
    <div className="space-y-md">
      <h1 className="font-display text-heading-sm font-bold uppercase">Moderation</h1>
      <div role="tablist" className="flex gap-xxs rounded-lg bg-surface-indigo p-xxs">
        {(["queue", "appeals", "audit"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={cn("min-h-10 rounded-md px-md text-link capitalize", tab === t ? "bg-primary text-on-primary" : "text-ink-soft")}>
            {t}
          </button>
        ))}
      </div>
      {tab === "queue" &&
        (queue.isLoading ? <PageSpinner /> : queue.isError ? <ErrorState message={errorMessage(queue.error)} /> : !queue.data?.items.length ? (
          <EmptyState title="Queue is clear">Nothing flagged right now.</EmptyState>
        ) : (
          <ul className="space-y-md">{queue.data.items.map((i) => <QueueCard key={`${i.entity_type}-${i.entity_id}`} item={i} />)}</ul>
        ))}
      {tab === "appeals" &&
        (appeals.isLoading ? <PageSpinner /> : !appeals.data?.items.length ? (
          <EmptyState title="No open appeals" />
        ) : (
          <ul className="space-y-sm">
            {appeals.data.items.map((a) => (
              <li key={a.id} className="rounded-lg bg-surface-indigo p-xl">
                <p className="text-link-sm text-ink-faint">Action {a.action_id.slice(0, 8)} · {timeAgo(a.created_at)}</p>
                <p className="mt-xs whitespace-pre-line text-body">{a.message}</p>
                <div className="mt-sm flex gap-xs">
                  <Button size="sm" variant="green" onClick={() => resolve.mutate({ id: a.id, accept: true, note: "" })}>Accept & reverse</Button>
                  <Button size="sm" variant="ghost" onClick={() => resolve.mutate({ id: a.id, accept: false, note: "" })}>Decline</Button>
                </div>
              </li>
            ))}
          </ul>
        ))}
      {tab === "audit" &&
        (audit.isLoading ? <PageSpinner /> : (
          <div className="overflow-x-auto rounded-lg">
            <table className="w-full text-left text-body">
              <thead className="bg-surface-indigo text-link-sm">
                <tr><th className="px-md py-sm">When</th><th className="px-md py-sm">Action</th><th className="px-md py-sm">Entity</th><th className="px-md py-sm">Reason</th></tr>
              </thead>
              <tbody>
                {audit.data?.items.map((a) => (
                  <tr key={a.id} className="border-b border-hairline">
                    <td className="px-md py-sm text-ink-soft">{timeAgo(a.created_at)}</td>
                    <td className="px-md py-sm">{a.action}</td>
                    <td className="px-md py-sm text-ink-soft">{a.entity_type} {a.entity_id.slice(0, 8)}</td>
                    <td className="px-md py-sm text-ink-soft">{a.reason || "-"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}
