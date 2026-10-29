import { useState } from "react";
import { toast } from "sonner";

import { uploadMedia, validateFile } from "@/api/media";
import { useUpdateMe } from "@/api/users";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Card, SectionTitle } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { useAuth } from "@/store/auth";

export default function ProfileSettings() {
  const user = useAuth((s) => s.user);
  const update = useUpdateMe();
  const [form, setForm] = useState({
    display_name: user?.display_name ?? "",
    handle: user?.handle ?? "",
    headline: user?.headline ?? "",
    bio: user?.bio ?? "",
    profession: user?.profession ?? "",
    location: user?.location ?? "",
    frustrated_status: user?.frustrated_status ?? "",
    links: (user?.links ?? []).join("\n"),
  });
  const [uploading, setUploading] = useState<"avatar" | "cover" | null>(null);
  if (!user) return null;
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setForm({ ...form, [k]: e.target.value });

  const save = (e: React.FormEvent) => {
    e.preventDefault();
    const { handle, links, ...rest } = form;
    update.mutate(
      { ...rest, ...(handle !== user.handle ? { handle } : {}), links: links.split(/\s+/).filter(Boolean).slice(0, 3) },
      { onSuccess: () => toast.success("Profile saved"), onError: (err) => toast.error(errorMessage(err)) },
    );
  };

  const upload = async (file: File | undefined, purpose: "avatar" | "cover") => {
    if (!file) return;
    const problem = await validateFile(file, purpose);
    if (problem) return toast.error(problem);
    setUploading(purpose);
    try {
      const media = await uploadMedia(file, purpose);
      await update.mutateAsync(purpose === "avatar" ? { avatar_media_id: media.id } : { cover_media_id: media.id });
      toast.success(purpose === "avatar" ? "Avatar updated" : "Cover updated");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setUploading(null);
    }
  };

  return (
    <>
      <Card>
        <SectionTitle>Pictures</SectionTitle>
        <p className="mt-xxs text-link-sm text-ink-faint">Location and camera data are stripped from every upload.</p>
        <div className="mt-md flex flex-wrap items-center gap-md">
          <Avatar src={user.avatar?.["400"]} name={user.display_name} size="lg" />
          <div className="flex flex-wrap gap-xs">
            <Button asChild variant="ghost" size="sm" loading={uploading === "avatar"}>
              <label className="cursor-pointer">
                {uploading === "avatar" ? "Uploading..." : "Change avatar"}
                <input type="file" accept="image/*" hidden disabled={!!uploading} onChange={(e) => void upload(e.target.files?.[0], "avatar")} />
              </label>
            </Button>
            <Button asChild variant="ghost" size="sm">
              <label className="cursor-pointer">
                {uploading === "cover" ? "Uploading..." : "Change cover"}
                <input type="file" accept="image/*" hidden disabled={!!uploading} onChange={(e) => void upload(e.target.files?.[0], "cover")} />
              </label>
            </Button>
            {user.avatar && <Button variant="quiet" size="sm" onClick={() => update.mutate({ remove_avatar: true })}>Remove avatar</Button>}
          </div>
        </div>
        {!user.email_verified && <p className="mt-sm text-link-sm text-ink-faint">Verify your email to upload pictures.</p>}
      </Card>
      <Card>
        <SectionTitle>About you</SectionTitle>
        <form onSubmit={save} className="mt-md space-y-md">
          <div className="grid gap-md tablet:grid-cols-2">
            <Field label="Display name" htmlFor="display_name"><Input id="display_name" maxLength={50} value={form.display_name} onChange={set("display_name")} /></Field>
            <Field label="Handle" htmlFor="handle" hint="Can be changed once every 30 days."><Input id="handle" maxLength={30} value={form.handle} onChange={(e) => setForm({ ...form, handle: e.target.value.toLowerCase() })} /></Field>
          </div>
          <Field label="Headline" htmlFor="headline" hint='e.g. "Backend dev, fighting legacy code"'><Input id="headline" maxLength={120} value={form.headline} onChange={set("headline")} /></Field>
          <Field label="Currently frustrated by..." htmlFor="frustrated_status"><Input id="frustrated_status" maxLength={100} value={form.frustrated_status} onChange={set("frustrated_status")} /></Field>
          <Field label="Bio" htmlFor="bio" hint={`${form.bio.length}/300`}><Textarea id="bio" maxLength={300} value={form.bio} onChange={set("bio")} /></Field>
          <div className="grid gap-md tablet:grid-cols-2">
            <Field label="Profession / industry" htmlFor="profession"><Input id="profession" maxLength={80} value={form.profession} onChange={set("profession")} /></Field>
            <Field label="City" htmlFor="location"><Input id="location" maxLength={80} value={form.location} onChange={set("location")} /></Field>
          </div>
          <Field label="Links (up to 3, one per line)" htmlFor="links"><Textarea id="links" className="min-h-20" value={form.links} onChange={set("links")} /></Field>
          <div className="flex justify-end"><Button type="submit" loading={update.isPending}>Save profile</Button></div>
        </form>
      </Card>
    </>
  );
}
