import "./styles/tokens.css";
import "./styles/fonts.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode, StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { Toaster } from "sonner";

import { PageSpinner } from "./components/ui/spinner";
import { ApiError, refreshSession } from "./lib/api";
import { router } from "./routes";
import { useAuth } from "./store/auth";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Retry transient failures (network / 5xx) with backoff; never retry client errors.
      retry: (count, err) => !(err instanceof ApiError && err.status >= 400 && err.status < 500) && count < 2,
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 8000),
    },
    mutations: { retry: false },
  },
});

// Viewer-specific fields (is_own, my_reaction, can_edit...) depend on who is logged in:
// refetch everything whenever the identity changes.
useAuth.subscribe((state, prev) => {
  if (state.user?.id !== prev.user?.id && prev.status !== "loading") void queryClient.invalidateQueries();
});

// Restore the session from the httpOnly refresh cookie, then keep the access token fresh.
void refreshSession().then((ok) => {
  if (!ok) useAuth.getState().clear();
});
setInterval(() => {
  const { status, expiresAt } = useAuth.getState();
  if (status === "authenticated" && expiresAt - Date.now() < 90_000) void refreshSession();
}, 30_000);

/** Render nothing viewer-dependent until the session bootstrap has finished (one fast request). */
function AuthGate({ children }: { children: ReactNode }) {
  const status = useAuth((s) => s.status);
  if (status === "loading") {
    return (
      <div className="flex min-h-screen items-center justify-center" aria-busy="true">
        <PageSpinner />
      </div>
    );
  }
  return <>{children}</>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <RouterProvider router={router} />
      </AuthGate>
      <Toaster
        theme="dark"
        position="bottom-center"
        toastOptions={{ className: "!bg-canvas !text-ink !border-indigo-line !rounded-lg !text-body" }}
      />
    </QueryClientProvider>
  </StrictMode>,
);
