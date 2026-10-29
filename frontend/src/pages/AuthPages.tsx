import { zodResolver } from "@hookform/resolvers/zod";
import { useEffect, useRef, useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";
import { z } from "zod";

import { authApi, useLogin, useOnboarding, useSignup } from "@/api/auth";
import { GoogleButton } from "@/components/GoogleButton";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { PageSpinner } from "@/components/ui/spinner";
import { errorMessage, refreshSession } from "@/lib/api";
import { useAuth } from "@/store/auth";

const GOOGLE_ERRORS: Record<string, string> = {
  google_cancelled: "Google sign-in was cancelled.",
  oauth_failed: "Google sign-in failed. Please try again.",
  account_banned: "This account has been banned.",
  google_in_use: "That Google account is linked to another Toxic-Express account.",
  google_disabled: "Google sign-in isn't available right now.",
};

/** Only allow same-site relative redirects (prevents open redirects via ?next=). */
export function safeNext(next: string | null): string {
  return next && next.startsWith("/") && !next.startsWith("//") ? next : "/";
}

/** DESIGN.md `ex-auth-form-card`. */
function AuthCard({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div className="w-full max-w-[28rem] rounded-lg border border-indigo-line bg-canvas p-xl shadow-modal">
      <h1 className="font-display text-heading-sm font-bold uppercase">{title}</h1>
      {subtitle && <p className="mt-xxs text-link-sm text-ink-soft">{subtitle}</p>}
      <div className="mt-xl">{children}</div>
    </div>
  );
}

function Divider() {
  return (
    <div className="my-md flex items-center gap-sm text-link-sm text-ink-faint">
      <span className="h-px flex-1 bg-indigo-line" /> or <span className="h-px flex-1 bg-indigo-line" />
    </div>
  );
}

const passwordRule = z
  .string()
  .min(10, "At least 10 characters")
  .max(128, "At most 128 characters")
  .refine((v) => new Set(v).size >= 5, "Too repetitive");

const handleRule = z
  .string()
  .min(3, "3-30 characters")
  .max(30, "3-30 characters")
  .regex(/^[a-z0-9_]+$/, "Lowercase letters, numbers and underscores only");

// --- Login -------------------------------------------------------------------------------------

const loginSchema = z.object({ email: z.string().email("Enter a valid email"), password: z.string().min(1, "Required") });

export function LoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const login = useLogin();
  const form = useForm<z.infer<typeof loginSchema>>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "" },
  });
  const googleError = params.get("error");

  const onSubmit = form.handleSubmit((values) =>
    login.mutate(values, { onSuccess: () => navigate(safeNext(params.get("next")), { replace: true }) }),
  );

  return (
    <AuthCard title="Welcome back" subtitle="Your rants missed you.">
      {googleError && (
        <p role="alert" className="mb-md rounded-sm bg-surface-indigo p-sm text-link-sm text-danger">
          {GOOGLE_ERRORS[googleError] ?? "Sign-in failed."}
        </p>
      )}
      <GoogleButton />
      <Divider />
      <form onSubmit={onSubmit} className="space-y-md" noValidate>
        <Field label="Email" htmlFor="email" error={form.formState.errors.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!form.formState.errors.email} {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={form.formState.errors.password?.message}>
          <Input id="password" type="password" autoComplete="current-password" aria-invalid={!!form.formState.errors.password} {...form.register("password")} />
        </Field>
        {login.isError && <p role="alert" className="text-link-sm text-danger">{errorMessage(login.error)}</p>}
        <Button type="submit" className="w-full" loading={login.isPending}>Log in</Button>
      </form>
      <div className="mt-md flex justify-between text-link-sm">
        <Link to="/forgot-password" className="text-link-cyan hover:underline">Forgot password?</Link>
        <Link to="/signup" className="text-link-cyan hover:underline">Create an account</Link>
      </div>
    </AuthCard>
  );
}

// --- Signup ------------------------------------------------------------------------------------

const signupSchema = z.object({
  display_name: z.string().trim().min(1, "Required").max(50),
  handle: handleRule,
  email: z.string().email("Enter a valid email"),
  password: passwordRule,
});

export function SignupPage() {
  const navigate = useNavigate();
  const signup = useSignup();
  const form = useForm<z.infer<typeof signupSchema>>({
    resolver: zodResolver(signupSchema),
    defaultValues: { display_name: "", handle: "", email: "", password: "" },
  });
  const e = form.formState.errors;
  const onSubmit = form.handleSubmit((values) =>
    signup.mutate(values, {
      onSuccess: () => {
        toast.success("Welcome to Toxic-Express! Check your inbox to verify your email.");
        navigate("/", { replace: true });
      },
    }),
  );
  return (
    <AuthCard title="Join Toxic-Express" subtitle="Scream it out. Get heard. Help others.">
      <GoogleButton label="Sign up with Google" />
      <Divider />
      <form onSubmit={onSubmit} className="space-y-md" noValidate>
        <Field label="Display name" htmlFor="display_name" error={e.display_name?.message}>
          <Input id="display_name" autoComplete="name" aria-invalid={!!e.display_name} {...form.register("display_name")} />
        </Field>
        <Field label="Handle" htmlFor="handle" error={e.handle?.message} hint="Your @name. Lowercase, numbers, underscores.">
          <Input id="handle" autoComplete="username" aria-invalid={!!e.handle} {...form.register("handle", { setValueAs: (v: string) => v.toLowerCase().trim() })} />
        </Field>
        <Field label="Email" htmlFor="email" error={e.email?.message}>
          <Input id="email" type="email" autoComplete="email" aria-invalid={!!e.email} {...form.register("email")} />
        </Field>
        <Field label="Password" htmlFor="password" error={e.password?.message} hint="10+ characters. A passphrase works great.">
          <Input id="password" type="password" autoComplete="new-password" aria-invalid={!!e.password} {...form.register("password")} />
        </Field>
        {signup.isError && <p role="alert" className="text-link-sm text-danger">{errorMessage(signup.error)}</p>}
        <Button type="submit" variant="green" className="w-full font-display uppercase" loading={signup.isPending}>Create account</Button>
        <p className="text-link-sm text-ink-faint">
          By joining you agree to rant about situations, not people. <Link to="/help#rules" className="text-link-cyan underline">Community rules</Link>
        </p>
      </form>
      <p className="mt-md text-link-sm">
        Already have an account? <Link to="/login" className="text-link-cyan hover:underline">Log in</Link>
      </p>
    </AuthCard>
  );
}

// --- Password reset ----------------------------------------------------------------------------

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const submit = async (ev: React.FormEvent) => {
    ev.preventDefault();
    setBusy(true);
    try {
      await authApi.forgotPassword(email);
      setSent(true);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <AuthCard title="Reset password" subtitle="We'll email you a link if an account exists.">
      {sent ? (
        <p className="text-body text-ink-soft">If that email is registered, a reset link is on its way. It expires in an hour.</p>
      ) : (
        <form onSubmit={submit} className="space-y-md">
          <Field label="Email" htmlFor="email">
            <Input id="email" type="email" required value={email} onChange={(ev) => setEmail(ev.target.value)} />
          </Field>
          <Button type="submit" className="w-full" loading={busy}>Send reset link</Button>
        </form>
      )}
      <p className="mt-md text-link-sm"><Link to="/login" className="text-link-cyan hover:underline">Back to log in</Link></p>
    </AuthCard>
  );
}

export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const token = params.get("token") ?? "";
  const schema = z.object({ password: passwordRule });
  const form = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema), defaultValues: { password: "" } });
  const [error, setError] = useState<string | null>(null);
  const onSubmit = form.handleSubmit(async ({ password }) => {
    try {
      await authApi.resetPassword(token, password);
      toast.success("Password updated. Log in with your new password.");
      navigate("/login", { replace: true });
    } catch (err) {
      setError(errorMessage(err));
    }
  });
  if (!token) return <Navigate to="/forgot-password" replace />;
  return (
    <AuthCard title="Choose a new password" subtitle="This signs you out everywhere else.">
      <form onSubmit={onSubmit} className="space-y-md" noValidate>
        <Field label="New password" htmlFor="password" error={form.formState.errors.password?.message}>
          <Input id="password" type="password" autoComplete="new-password" {...form.register("password")} />
        </Field>
        {error && <p role="alert" className="text-link-sm text-danger">{error}</p>}
        <Button type="submit" className="w-full" loading={form.formState.isSubmitting}>Update password</Button>
      </form>
    </AuthCard>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const [state, setState] = useState<"working" | "ok" | "error">("working");
  const [message, setMessage] = useState("");
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return; // tokens are single use; avoid StrictMode double calls
    ran.current = true;
    authApi
      .verifyEmail(token)
      .then(async () => {
        setState("ok");
        await refreshSession();
      })
      .catch((err) => {
        setState("error");
        setMessage(errorMessage(err));
      });
  }, [token]);
  return (
    <AuthCard title="Email verification">
      {state === "working" && <PageSpinner />}
      {state === "ok" && (
        <>
          <p className="text-body">Your email is verified. You can now add images and video to your rants.</p>
          <Button asChild className="mt-md w-full"><Link to="/">Go to my feed</Link></Button>
        </>
      )}
      {state === "error" && <p role="alert" className="text-body text-danger">{message}</p>}
    </AuthCard>
  );
}

// --- Google callback & onboarding --------------------------------------------------------------

export function AuthCallbackPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const ran = useRef(false);
  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    void refreshSession().then((ok) => {
      if (!ok) return navigate("/login?error=oauth_failed", { replace: true });
      const user = useAuth.getState().user;
      navigate(params.get("new") === "1" || (user && !user.onboarded) ? "/onboarding" : "/", { replace: true });
    });
  }, [navigate, params]);
  return <PageSpinner />;
}

export function OnboardingPage() {
  const user = useAuth((s) => s.user);
  const navigate = useNavigate();
  const onboarding = useOnboarding();
  const schema = z.object({
    handle: handleRule,
    display_name: z.string().trim().min(1, "Required").max(50),
    headline: z.string().trim().max(120),
  });
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { handle: user?.handle ?? "", display_name: user?.display_name ?? "", headline: "" },
  });
  if (user?.onboarded) return <Navigate to="/" replace />;
  const e = form.formState.errors;
  const onSubmit = form.handleSubmit((values) =>
    onboarding.mutate(values, { onSuccess: () => navigate("/", { replace: true }) }),
  );
  return (
    <AuthCard title="Set up your profile" subtitle="We pre-filled this from Google. Change anything; you can stay low-key.">
      <form onSubmit={onSubmit} className="space-y-md" noValidate>
        <Field label="Handle" htmlFor="handle" error={e.handle?.message}>
          <Input id="handle" {...form.register("handle", { setValueAs: (v: string) => v.toLowerCase().trim() })} />
        </Field>
        <Field label="Display name" htmlFor="display_name" error={e.display_name?.message} hint="Doesn't have to be your real name.">
          <Input id="display_name" {...form.register("display_name")} />
        </Field>
        <Field label="Headline (optional)" htmlFor="headline" error={e.headline?.message} hint='e.g. "Backend dev, fighting legacy code"'>
          <Input id="headline" {...form.register("headline")} />
        </Field>
        {onboarding.isError && <p role="alert" className="text-link-sm text-danger">{errorMessage(onboarding.error)}</p>}
        <Button type="submit" variant="green" className="w-full font-display uppercase" loading={onboarding.isPending}>Let's go</Button>
      </form>
    </AuthCard>
  );
}
