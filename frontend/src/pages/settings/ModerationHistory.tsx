import { useState } from "react";
import { toast } from "sonner";

import { safetyApi } from "@/api/admin";
import { useMyModerationActions } from "@/api/users";
import { Button } from "@/components/ui/button";
import { Card, SectionTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Textarea } from "@/components/ui/input";
import { PageSpinner } from "@/components/ui/spinner";
import { errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/utils";

export default function ModerationHistory() {
  const { data, isLoading } = useMyModerationActions();
  const [open, setOpen] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [sent, setSent] = useState<Set<string>>(new Set());
  if (isLoading) return <PageSpinner />;
  if (!data?.length) return <EmptyState title="Clean record">No moderation actions on your account.</EmptyState>;
  return (
    <Card>
      <SectionTitle>Moderation history</SectionTitle>
      <p className="mt-xs text-link-sm text-ink-faint">You can appeal each decision once, within 30 days.</p>
      <ul className="mt-md space-y-sm">
        {data.map((a) => (
          <li key={a.id} className="rounded-md bg-canvas p-md">
            <p className="text-body capitalize">{a.action} · <span className="text-ink-faint">{a.entity_type} · {timeAgo(a.created_at)}</span></p>
            {a.reason && <p className="mt-xxs text-link-sm text-ink-soft">Reason: {a.reason}</p>}
            {sent.has(a.id) ? (
              <p className="mt-xs text-link-sm text-green">Appeal sent</p>
            ) : open === a.id ? (
              <form
                className="mt-sm space-y-xs"
                onSubmit={async (e) => {
                  e.preventDefault();
                  try {
                    await safetyApi.appeal(a.id, message);
                    setSent(new Set(sent).add(a.id));
                    setOpen(null);
                    setMessage("");
                    toast.success("Appeal sent to the moderators");
                  } catch (err) {
                    toast.error(errorMessage(err));
                  }
                }}
              >
                <Textarea aria-label="Appeal message" minLength={10} maxLength={1000} required value={message} onChange={(e) => setMessage(e.target.value)} placeholder="Explain why this decision should be reversed (10+ characters)" />
                <div className="flex justify-end gap-xs">
                  <Button type="button" size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
                  <Button type="submit" size="sm">Send appeal</Button>
                </div>
              </form>
            ) : (
              <Button size="sm" variant="ghost" className="mt-xs" onClick={() => setOpen(a.id)}>Appeal</Button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}
