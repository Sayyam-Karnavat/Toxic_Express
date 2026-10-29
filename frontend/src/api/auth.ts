import { useMutation, useQueryClient } from "@tanstack/react-query";

import { api, API_BASE } from "@/lib/api";
import { useAuth } from "@/store/auth";
import type { Me, TokenOut } from "@/types";

export function useLogin() {
  const setSession = useAuth((s) => s.setSession);
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      api<TokenOut>("/auth/login", { method: "POST", body, retryOn401: false }),
    onSuccess: setSession,
  });
}

export function useSignup() {
  const setSession = useAuth((s) => s.setSession);
  return useMutation({
    mutationFn: (body: { email: string; password: string; handle: string; display_name: string }) =>
      api<TokenOut>("/auth/signup", { method: "POST", body }),
    onSuccess: setSession,
  });
}

export function useLogout() {
  const qc = useQueryClient();
  const clear = useAuth((s) => s.clear);
  return useMutation({
    mutationFn: (everywhere: boolean = false) =>
      api(everywhere ? "/auth/logout-all" : "/auth/logout", { method: "POST" }),
    onSettled: () => {
      clear();
      qc.clear();
    },
  });
}

export function useOnboarding() {
  const setUser = useAuth((s) => s.setUser);
  return useMutation({
    mutationFn: (body: { handle: string; display_name: string; headline: string }) =>
      api<Me>("/me/onboarding", { method: "POST", body }),
    onSuccess: setUser,
  });
}

export const authApi = {
  verifyEmail: (token: string) => api("/auth/verify-email", { method: "POST", body: { token } }),
  resendVerification: () => api("/auth/resend-verification", { method: "POST" }),
  forgotPassword: (email: string) => api("/auth/forgot-password", { method: "POST", body: { email } }),
  resetPassword: (token: string, password: string) =>
    api("/auth/reset-password", { method: "POST", body: { token, password } }),
  setPassword: (password: string, current_password?: string) =>
    api("/auth/password", { method: "POST", body: { password, current_password } }),
  googleLinkUrl: () => api<{ url: string }>("/auth/google/link-url", { method: "POST" }),
  googleUnlink: () => api("/auth/google", { method: "DELETE" }),
};

export const GOOGLE_LOGIN_URL = `${API_BASE}/auth/google/login`;
