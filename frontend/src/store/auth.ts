import { create } from "zustand";

import type { Me, TokenOut } from "@/types";

type Status = "loading" | "authenticated" | "anonymous";

interface AuthState {
  status: Status;
  user: Me | null;
  accessToken: string | null;
  expiresAt: number;
  setSession: (tokens: TokenOut) => void;
  setUser: (user: Me) => void;
  clear: () => void;
}

/** The access token lives only in memory; the refresh token is an httpOnly cookie. */
export const useAuth = create<AuthState>((set) => ({
  status: "loading",
  user: null,
  accessToken: null,
  expiresAt: 0,
  setSession: (tokens) =>
    set({
      status: "authenticated",
      user: tokens.user,
      accessToken: tokens.access_token,
      expiresAt: Date.now() + tokens.expires_in * 1000,
    }),
  setUser: (user) => set({ user }),
  clear: () => set({ status: "anonymous", user: null, accessToken: null, expiresAt: 0 }),
}));
