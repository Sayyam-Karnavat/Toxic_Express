import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";

import { useAuth } from "@/store/auth";

import { PageSpinner } from "./ui/spinner";

export function RequireAuth({ children, allowOnboarding = false }: { children: ReactNode; allowOnboarding?: boolean }) {
  const { status, user } = useAuth();
  const location = useLocation();
  if (status === "loading") return <PageSpinner />;
  if (status === "anonymous") {
    return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  }
  if (!allowOnboarding && user && !user.onboarded) return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}

export function RequireMod({ children }: { children: ReactNode }) {
  const user = useAuth((s) => s.user);
  return (
    <RequireAuth>
      {user && (user.role === "mod" || user.role === "admin") ? children : <Navigate to="/" replace />}
    </RequireAuth>
  );
}

export function GuestOnly({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status);
  if (status === "loading") return <PageSpinner />;
  if (status === "authenticated") return <Navigate to="/" replace />;
  return <>{children}</>;
}
