import { ImagePlus, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { uploadMedia, validateFile } from "@/api/media";
import { useMeta } from "@/api/meta";
import { useCreatePost, useUpdatePost } from "@/api/posts";
import { useSettings } from "@/api/users";
import { ApiError, errorMessage } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import type { Category, Media, Post } from "@/types";

import { CrisisBanner } from "./CrisisBanner";
import { FrustrationPicker } from "./FrustrationMeter";
import { Button } from "./ui/button";
import { Dialog, DialogContent } from "./ui/dialog";
import { Field, Input, Label, Select, Textarea } from "./ui/input";
import { Switch } from "./ui/switch";

interface Attachment {
  key: string;
  file: File;
  preview: string;
  progress: number;
  media?: Media;
  error?: string;
}

const TAG_RE = /^[a-z0-9][a-z0-9-]{0,28}[a-z0-9]$/;

export function Composer({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  editing?: Post;
}) {
  const { data: meta } = useMeta();
  const { data: settings } = useSettings();
  const user = useAuth((s) => s.user);
  const navigate = useNavigate();
  const create = useCreatePost();
  const update = useUpdatePost(editing?.id ?? "");
  const fileInput = useRef<HTMLInputElement>(null);

  const [title, setTitle] = useState(editing?.title ?? "");
  const [body, setBody] = useState(editing?.body ?? "");
  const [category, setCategory] = useState<Category>(editing?.category ?? "work");
  const [tags, setTags] = useState<string[]>(editing?.tags ?? []);
  const [tagDraft, setTagDraft] = useState("");
  const [level, setLevel] = useState(editing?.frustration_level ?? 3);
  const [anonymous, setAnonymous] = useState<boolean | null>(editing ? editing.is_anonymous : null);
  const [warning, setWarning] = useState(editing?.content_warning ?? false);
  const [seekingAdvice, setSeekingAdvice] = useState(editing?.status === "seeking_advice");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [crisis, setCrisis] = useState<Post | null>(null);

  const isAnonymous = anonymous ?? settings?.privacy.default_anonymous ?? false;
  const uploading = attachments.some((a) => !a.media && !a.error);
  const failed = attachments.some((a) => a.error);
  const hasVideo = attachments.some((a) => a.file.type.startsWith("video/"));
  const limits = meta?.limits;

  useEffect(() => () => attachments.forEach((a) => URL.revokeObjectURL(a.preview)), [attachments]);

  const addTag = (raw: string) => {
    const tag = raw.trim().toLowerCase().replace(/^#/, "").replace(/\s+/g, "-");
    if (!tag) return;
    if (!TAG_RE.test(tag)) return setError("Tags: 2-30 letters, numbers or hyphens.");
    if (tags.length >= 5) return setError("Up to 5 tags.");
    if (!tags.includes(tag)) setTags([...tags, tag]);
    setTagDraft("");
    setError(null);
  };

  const addFiles = async (files: FileList | null) => {
    if (!files?.length) return;
    for (const file of Array.from(files)) {
      const isVideo = file.type.startsWith("video/");
      if (hasVideo || (isVideo && attachments.length) || attachments.length >= 4) {
        toast.error("Add up to 4 images, or 1 video.");
        break;
      }
      const problem = await validateFile(file, "post");
      if (problem) {
        toast.error(problem);
        continue;
      }
      const key = crypto.randomUUID();
      const item: Attachment = { key, file, preview: URL.createObjectURL(file), progress: 0 };
      setAttachments((prev) => [...prev, item]);
      uploadMedia(file, "post", (p) =>
        setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, progress: p } : a))),
      )
        .then((media) => setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, media } : a))))
        .catch((err) =>
          setAttachments((prev) => prev.map((a) => (a.key === key ? { ...a, error: errorMessage(err) } : a))),
        );
    }
  };

  const reset = () => {
    setTitle("");
    setBody("");
    setTags([]);
    setAttachments([]);
    setLevel(3);
    setWarning(false);
    setSeekingAdvice(false);
    setAnonymous(null);
    setError(null);
  };

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (title.trim().length < 3) return setError("Give your rant a title (3+ characters).");
    if (!body.trim()) return setError("Let it out: write something.");
    const status = seekingAdvice ? "seeking_advice" : "open";
    try {
      if (editing) {
        await update.mutateAsync({
          title, body, category, tags, frustration_level: level, content_warning: warning,
          ...(editing.status === "solved" ? {} : { status }),
        });
        toast.success("Rant updated");
        onOpenChange(false);
        return;
      }
      const post = await create.mutateAsync({
        title,
        body,
        category,
        tags,
        frustration_level: level,
        is_anonymous: isAnonymous,
        content_warning: warning,
        status,
        media_ids: attachments.flatMap((a) => (a.media ? [a.media.id] : [])),
      });
      reset();
      if (post.show_crisis_resources) {
        setCrisis(post);
        return;
      }
      onOpenChange(false);
      toast.success(post.moderation_state === "published" ? "Rant posted. Feel better?" : "Rant submitted for a quick check.");
      navigate(`/p/${post.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : errorMessage(err));
    }
  };

  if (crisis) {
    return (
      <Dialog open={open} onOpenChange={(v) => { onOpenChange(v); if (!v) setCrisis(null); }}>
        <DialogContent title="Your rant is up">
          <p className="text-body text-ink-soft">
            It sounds like things are really hard right now. People here care, and so do the folks below.
          </p>
          <CrisisBanner />
          <div className="mt-xl flex justify-end">
            <Button onClick={() => { onOpenChange(false); navigate(`/p/${crisis.id}`); setCrisis(null); }}>
              View my rant
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        title={editing ? "Edit rant" : "Scream it out"}
        description={editing ? `You can edit for ${limits?.edit_window_minutes ?? 15} minutes after posting.` : "Vent about the situation. Swearing is fine; exposing or threatening people isn't."}
        className="max-w-2xl"
      >
        <form onSubmit={submit} className="space-y-md" noValidate>
          <Field label="Title" htmlFor="rant-title">
            <Input id="rant-title" value={title} maxLength={limits?.title ?? 120} onChange={(e) => setTitle(e.target.value)} placeholder="What's driving you up the wall?" autoFocus />
          </Field>
          <Field label="Rant" htmlFor="rant-body" hint={`${body.length}/${limits?.body ?? 5000}. Markdown: **bold**, *italic*, lists, links.`}>
            <Textarea id="rant-body" value={body} maxLength={limits?.body ?? 5000} onChange={(e) => setBody(e.target.value)} rows={7} placeholder="Let it all out..." />
          </Field>
          <div className="grid gap-md tablet:grid-cols-2">
            <Field label="Category" htmlFor="rant-category">
              <Select id="rant-category" value={category} onChange={(e) => setCategory(e.target.value as Category)}>
                {meta?.categories.map((c) => (
                  <option key={c.value} value={c.value}>{c.label}</option>
                ))}
              </Select>
            </Field>
            <div>
              <Label htmlFor="rant-tags">Tags</Label>
              <Input
                id="rant-tags"
                value={tagDraft}
                placeholder={tags.length >= 5 ? "Max 5 tags" : "Type and press Enter"}
                disabled={tags.length >= 5}
                onChange={(e) => setTagDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === ",") {
                    e.preventDefault();
                    addTag(tagDraft);
                  }
                }}
                onBlur={() => addTag(tagDraft)}
              />
              {tags.length > 0 && (
                <div className="mt-xs flex flex-wrap gap-xs">
                  {tags.map((t) => (
                    <span key={t} className="inline-flex items-center gap-xxs rounded-pill bg-surface-indigo px-sm py-xxs text-link-sm">
                      #{t}
                      <button type="button" aria-label={`Remove tag ${t}`} onClick={() => setTags(tags.filter((x) => x !== t))}>
                        <X className="size-3.5" />
                      </button>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
          <div>
            <Label>Frustration meter</Label>
            <FrustrationPicker value={level} onChange={setLevel} />
          </div>

          {!editing && (
            <div>
              <Label>Media</Label>
              <div className="flex flex-wrap gap-sm">
                {attachments.map((a) => (
                  <div key={a.key} className="relative size-24 overflow-hidden rounded-md bg-surface-indigo">
                    {a.file.type.startsWith("video/") ? (
                      <video src={a.preview} className="size-full object-cover" muted />
                    ) : (
                      <img src={a.preview} alt="" className="size-full object-cover" />
                    )}
                    <div className={cn("absolute inset-0 flex items-center justify-center text-link-sm", !a.media && "bg-canvas/70")}>
                      {a.error ? (
                        <span className="p-xxs text-center text-danger">{a.error}</span>
                      ) : !a.media ? (
                        <span className="flex items-center gap-xxs">
                          <Loader2 className="size-4 animate-spin" aria-hidden />
                          {a.progress < 1 ? `${Math.round(a.progress * 100)}%` : "Checking"}
                        </span>
                      ) : null}
                    </div>
                    <button
                      type="button"
                      aria-label="Remove attachment"
                      onClick={() => setAttachments(attachments.filter((x) => x.key !== a.key))}
                      className="absolute right-xxs top-xxs rounded-full bg-canvas p-0.5"
                    >
                      <X className="size-4" />
                    </button>
                  </div>
                ))}
                {!hasVideo && attachments.length < 4 && (
                  <button
                    type="button"
                    onClick={() => fileInput.current?.click()}
                    disabled={!user?.email_verified}
                    title={user?.email_verified ? undefined : "Verify your email to add media"}
                    className="flex size-24 flex-col items-center justify-center gap-xxs rounded-md border border-dashed border-indigo-line text-link-sm text-ink-soft hover:border-primary disabled:opacity-50"
                  >
                    <ImagePlus className="size-6" aria-hidden />
                    Add
                  </button>
                )}
                <input
                  ref={fileInput}
                  type="file"
                  hidden
                  multiple
                  accept="image/jpeg,image/png,image/webp,image/heic,video/mp4,video/quicktime,video/webm"
                  onChange={(e) => {
                    void addFiles(e.target.files);
                    e.target.value = "";
                  }}
                />
              </div>
              {!user?.email_verified && <p className="mt-xxs text-link-sm text-ink-faint">Verify your email to attach images or video.</p>}
            </div>
          )}

          <div className="rounded-lg bg-surface-indigo px-md py-xs">
            {!editing && (
              <Switch id="rant-anon" checked={isAnonymous} onCheckedChange={setAnonymous} label="Post anonymously" description="Your name never appears on this rant. Moderators can still see who posted it." />
            )}
            <Switch id="rant-advice" checked={seekingAdvice} onCheckedChange={setSeekingAdvice} label="I'm looking for advice" description="Invite people to help solve it, not just relate." />
            <Switch id="rant-cw" checked={warning} onCheckedChange={setWarning} label="Content warning" description="Hide the text and blur media until readers choose to view." />
          </div>

          {error && <p role="alert" className="rounded-sm bg-surface-indigo p-sm text-link-sm text-danger">{error}</p>}

          <div className="flex justify-end gap-sm">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" variant="green" loading={create.isPending || update.isPending} disabled={uploading || failed} className="font-display uppercase">
              {uploading ? "Uploading..." : failed ? "Remove failed media" : editing ? "Save" : "Scream it"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
