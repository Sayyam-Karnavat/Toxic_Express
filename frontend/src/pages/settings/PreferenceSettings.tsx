import { X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { useMeta } from "@/api/meta";
import { useBlockedMuted, useSettings, useUpdateSettings } from "@/api/users";
import { UserRow } from "@/components/UserRow";
import { Button } from "@/components/ui/button";
import { Card, SectionTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Input, Label, Select } from "@/components/ui/input";
import { PageSpinner } from "@/components/ui/spinner";
import { Switch } from "@/components/ui/switch";
import { api, errorMessage } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { keys } from "@/api/keys";
import type { Category, Settings } from "@/types";

function useSave() {
  const update = useUpdateSettings();
  return (patch: Partial<Settings>) =>
    update.mutate(patch, { onSuccess: () => toast.success("Saved"), onError: (e) => toast.error(errorMessage(e)) });
}

export function PrivacySettings() {
  const { data } = useSettings();
  const save = useSave();
  if (!data) return <PageSpinner />;
  const p = data.privacy;
  const set = (patch: Partial<typeof p>) => save({ privacy: { ...p, ...patch } });
  return (
    <Card>
      <SectionTitle>Privacy</SectionTitle>
      <div className="mt-md divide-y divide-indigo-line">
        <Switch id="p-anon" checked={p.default_anonymous ?? false} onCheckedChange={(v) => set({ default_anonymous: v })} label="Post anonymously by default" description="You can still switch it per rant." />
        <Switch id="p-search" checked={p.searchable ?? true} onCheckedChange={(v) => set({ searchable: v })} label="Show me in people search" />
        <Switch id="p-prof" checked={p.hide_profession ?? false} onCheckedChange={(v) => set({ hide_profession: v })} label="Hide my profession" />
        <Switch id="p-loc" checked={p.hide_location ?? false} onCheckedChange={(v) => set({ hide_location: v })} label="Hide my city" />
        <div className="py-sm">
          <Label htmlFor="p-comment">Who can respond to my rants</Label>
          <Select id="p-comment" value={p.who_can_comment ?? "everyone"} onChange={(e) => set({ who_can_comment: e.target.value as "everyone" | "followers" | "none" })}>
            <option value="everyone">Everyone</option>
            <option value="followers">People who follow me</option>
            <option value="none">Nobody</option>
          </Select>
        </div>
      </div>
    </Card>
  );
}

export function ContentSettings() {
  const { data } = useSettings();
  const { data: meta } = useMeta();
  const save = useSave();
  const [word, setWord] = useState("");
  if (!data) return <PageSpinner />;
  const c = data.content;
  const set = (patch: Partial<typeof c>) => save({ content: { ...c, ...patch } });
  const muted = c.muted_words ?? [];
  const mutedCats = c.muted_categories ?? [];
  return (
    <Card>
      <SectionTitle>Content preferences</SectionTitle>
      <div className="mt-md divide-y divide-indigo-line">
        <Switch id="c-blur" checked={c.blur_sensitive_media ?? true} onCheckedChange={(v) => set({ blur_sensitive_media: v })} label="Blur media on content-warning rants" />
        <Switch id="c-cw" checked={c.hide_content_warning_posts ?? false} onCheckedChange={(v) => set({ hide_content_warning_posts: v })} label="Hide content-warning rants entirely" />
      </div>
      <div className="mt-md">
        <Label htmlFor="mute-word">Muted words</Label>
        <form
          className="flex gap-xs"
          onSubmit={(e) => {
            e.preventDefault();
            const w = word.trim().toLowerCase();
            if (w.length >= 2 && !muted.includes(w)) set({ muted_words: [...muted, w] });
            setWord("");
          }}
        >
          <Input id="mute-word" value={word} maxLength={40} onChange={(e) => setWord(e.target.value)} placeholder="e.g. crypto" />
          <Button type="submit" variant="ghost">Mute</Button>
        </form>
        <div className="mt-xs flex flex-wrap gap-xs">
          {muted.map((w) => (
            <span key={w} className="inline-flex items-center gap-xxs rounded-pill bg-canvas px-sm py-xxs text-link-sm">
              {w}
              <button aria-label={`Unmute ${w}`} onClick={() => set({ muted_words: muted.filter((x) => x !== w) })}><X className="size-3.5" /></button>
            </span>
          ))}
        </div>
      </div>
      <fieldset className="mt-md">
        <legend className="mb-xs text-link-sm font-medium text-ink-soft">Hide these categories</legend>
        <div className="flex flex-wrap gap-xs">
          {meta?.categories.map((cat) => {
            const on = mutedCats.includes(cat.value);
            return (
              <button
                key={cat.value}
                type="button"
                aria-pressed={on}
                onClick={() => set({ muted_categories: on ? mutedCats.filter((x) => x !== cat.value) : [...mutedCats, cat.value as Category] })}
                className={on ? "rounded-pill bg-magenta-strong px-sm py-xs text-link-sm" : "rounded-pill bg-canvas px-sm py-xs text-link-sm text-ink-soft"}
              >
                {cat.label}
              </button>
            );
          })}
        </div>
      </fieldset>
    </Card>
  );
}

export function NotificationSettings() {
  const { data } = useSettings();
  const save = useSave();
  if (!data) return <PageSpinner />;
  const n = data.notifications;
  const set = (patch: Partial<typeof n>) => save({ notifications: { ...n, ...patch } });
  const rows: [keyof typeof n, string][] = [
    ["reactions", "Reactions to my rants"],
    ["comments", "Responses to my rants"],
    ["replies", "Replies to my comments"],
    ["follows", "New followers"],
    ["solved", "When my comment helps solve a rant"],
    ["helpful", "When my comment is marked helpful"],
  ];
  return (
    <Card>
      <SectionTitle>Notifications</SectionTitle>
      <div className="mt-md divide-y divide-indigo-line">
        {rows.map(([key, label]) => (
          <Switch key={key} id={`n-${key}`} checked={(n[key] as boolean | undefined) ?? true} onCheckedChange={(v) => set({ [key]: v })} label={label} />
        ))}
      </div>
      <p className="mt-md text-link-sm text-ink-faint">Moderation and safety notices are always delivered.</p>
    </Card>
  );
}

export function BlockedSettings() {
  const qc = useQueryClient();
  const blocks = useBlockedMuted("blocks");
  const mutes = useBlockedMuted("mutes");
  const undo = async (kind: "blocks" | "mutes", id: string) => {
    try {
      await api(`/me/${kind}/${id}`, { method: "DELETE" });
      await qc.invalidateQueries({ queryKey: kind === "blocks" ? keys.blocks : keys.mutes });
      void qc.invalidateQueries({ queryKey: keys.feedRoot });
    } catch (e) {
      toast.error(errorMessage(e));
    }
  };
  return (
    <>
      {(["blocks", "mutes"] as const).map((kind) => {
        const q = kind === "blocks" ? blocks : mutes;
        return (
          <Card key={kind}>
            <SectionTitle>{kind === "blocks" ? "Blocked" : "Muted"}</SectionTitle>
            {q.isLoading ? <PageSpinner /> : !q.data?.length ? (
              <div className="mt-md"><EmptyState title={kind === "blocks" ? "Nobody blocked" : "Nobody muted"} /></div>
            ) : (
              <ul className="mt-md space-y-xs">
                {q.data.map((u) => (
                  <UserRow key={u.id} user={u} action={<Button size="sm" variant="quiet" onClick={() => void undo(kind, u.id)}>{kind === "blocks" ? "Unblock" : "Unmute"}</Button>} />
                ))}
              </ul>
            )}
          </Card>
        );
      })}
    </>
  );
}
