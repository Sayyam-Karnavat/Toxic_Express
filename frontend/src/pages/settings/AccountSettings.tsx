import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { authApi, useLogout } from "@/api/auth";
import { keys } from "@/api/keys";
import { refreshMe, useSessions } from "@/api/users";
import { GoogleMark } from "@/components/GoogleButton";
import { Button } from "@/components/ui/button";
import { Card, SectionTitle } from "@/components/ui/card";
import { Field, Input } from "@/components/ui/input";
import { api, errorMessage } from "@/lib/api";
import { timeAgo } from "@/lib/utils";
import { useAuth } from "@/store/auth";
import type { Me } from "@/types";

export default function AccountSettings() {
  const user = useAuth((s) => s.user);
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const logout = useLogout();
  const sessions = useSessions();
  const [email, setEmail] = useState("");
  const [emailPassword, setEmailPassword] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [deletePassword, setDeletePassword] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  if (!user) return null;

  const run = async (key: string, fn: () => Promise<unknown>, success: string) => {
    setBusy(key);
    try {
      await fn();
      toast.success(success);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const exportData = () =>
    run("export", async () => {
      const data = await api<unknown>("/me/export");
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = Object.assign(document.createElement("a"), { href: url, download: `toxic-express-${user.handle}.json` });
      a.click();
      URL.revokeObjectURL(url);
    }, "Export downloaded");

  return (
    <>
      {params.get("linked") === "google" && (
        <p role="status" className="rounded-lg bg-surface-indigo p-md text-body">Google account linked.</p>
      )}
      <Card>
        <SectionTitle>Email</SectionTitle>
        <p className="mt-xs text-body">
          {user.email} · {user.email_verified ? <span className="text-green">verified</span> : <span className="text-danger">not verified</span>}
        </p>
        {!user.email_verified && (
          <Button size="sm" variant="ghost" className="mt-sm" loading={busy === "resend"} onClick={() => run("resend", authApi.resendVerification, "Verification email sent")}>
            Resend verification email
          </Button>
        )}
        <form
          className="mt-md grid gap-md tablet:grid-cols-[1fr_1fr_auto] tablet:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            void run("email", async () => {
              useAuth.getState().setUser(await api<Me>("/me/email", { method: "POST", body: { email, password: emailPassword || null } }));
              setEmail("");
              setEmailPassword("");
            }, "Email changed. Check your inbox to verify it.");
          }}
        >
          <Field label="New email" htmlFor="new-email"><Input id="new-email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
          {user.has_password && <Field label="Current password" htmlFor="email-pw"><Input id="email-pw" type="password" required value={emailPassword} onChange={(e) => setEmailPassword(e.target.value)} /></Field>}
          <Button type="submit" loading={busy === "email"}>Change email</Button>
        </form>
      </Card>

      <Card>
        <SectionTitle>{user.has_password ? "Change password" : "Set a password"}</SectionTitle>
        {!user.has_password && <p className="mt-xs text-link-sm text-ink-faint">You sign in with Google. Add a password to also log in with email.</p>}
        <form
          className="mt-md grid gap-md tablet:grid-cols-[1fr_1fr_auto] tablet:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            void run("password", async () => {
              await authApi.setPassword(next, user.has_password ? current : undefined);
              await refreshMe();
              setCurrent("");
              setNext("");
            }, "Password saved");
          }}
        >
          {user.has_password && <Field label="Current password" htmlFor="cur-pw"><Input id="cur-pw" type="password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} /></Field>}
          <Field label="New password" htmlFor="new-pw" hint="10+ characters"><Input id="new-pw" type="password" autoComplete="new-password" required minLength={10} value={next} onChange={(e) => setNext(e.target.value)} /></Field>
          <Button type="submit" loading={busy === "password"}>Save password</Button>
        </form>
      </Card>

      <Card>
        <SectionTitle>Google</SectionTitle>
        <div className="mt-md flex flex-wrap items-center justify-between gap-md">
          <p className="flex items-center gap-sm text-body"><GoogleMark /> {user.google_linked ? "Connected" : "Not connected"}</p>
          {user.google_linked ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={!user.has_password}
              title={user.has_password ? undefined : "Set a password first so you don't get locked out"}
              loading={busy === "unlink"}
              onClick={() => run("unlink", async () => { await authApi.googleUnlink(); await refreshMe(); }, "Google disconnected")}
            >
              Disconnect
            </Button>
          ) : (
            <Button variant="ghost" size="sm" loading={busy === "link"} onClick={() => run("link", async () => { window.location.href = (await authApi.googleLinkUrl()).url; }, "Redirecting to Google...")}>
              Connect Google
            </Button>
          )}
        </div>
        {user.google_linked && !user.has_password && <p className="mt-xs text-link-sm text-ink-faint">Set a password before disconnecting Google.</p>}
      </Card>

      <Card>
        <SectionTitle>Active sessions</SectionTitle>
        <ul className="mt-md space-y-xs">
          {sessions.data?.map((s) => (
            <li key={s.id} className="flex items-center justify-between gap-sm rounded-md bg-canvas p-sm">
              <span className="min-w-0 text-link-sm">
                <span className="block truncate">{s.user_agent || "Unknown device"}</span>
                <span className="text-ink-faint">{s.ip} · active {timeAgo(s.last_used_at)}{s.current && " · this device"}</span>
              </span>
              {!s.current && (
                <Button size="sm" variant="quiet" onClick={() => run(`s-${s.id}`, async () => { await api(`/me/sessions/${s.id}`, { method: "DELETE" }); await qc.invalidateQueries({ queryKey: keys.sessions }); }, "Session signed out")}>
                  Sign out
                </Button>
              )}
            </li>
          ))}
        </ul>
        <Button variant="ghost" size="sm" className="mt-md" onClick={() => logout.mutate(true, { onSettled: () => navigate("/login") })}>
          Log out everywhere
        </Button>
      </Card>

      <Card>
        <SectionTitle>Your data</SectionTitle>
        <p className="mt-xs text-body text-ink-soft">Download everything you've posted, your settings and who you follow.</p>
        <Button variant="ghost" size="sm" className="mt-md" loading={busy === "export"} onClick={exportData}>Export my data (JSON)</Button>
      </Card>

      <Card className="border border-danger/40">
        <SectionTitle className="text-danger">Delete account</SectionTitle>
        <p className="mt-xs text-body text-ink-soft">Your profile and content are hidden right away and permanently deleted after 30 days. Log in before then to cancel.</p>
        <form
          className="mt-md grid gap-md tablet:grid-cols-[1fr_auto] tablet:items-end"
          onSubmit={(e) => {
            e.preventDefault();
            if (!window.confirm("Delete your account? You have 30 days to change your mind.")) return;
            void run("delete", async () => {
              await api("/me", { method: "DELETE", body: { password: deletePassword || null, confirm: "DELETE" } });
              useAuth.getState().clear();
              qc.clear();
              navigate("/");
            }, "Account scheduled for deletion");
          }}
        >
          {user.has_password && <Field label="Password" htmlFor="del-pw"><Input id="del-pw" type="password" required value={deletePassword} onChange={(e) => setDeletePassword(e.target.value)} /></Field>}
          <Button type="submit" variant="danger" loading={busy === "delete"}>Delete my account</Button>
        </form>
      </Card>
    </>
  );
}
