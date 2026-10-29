import { useAuth } from "@/store/auth";
import type { TokenOut } from "@/types";

export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? "/api/v1";
const CSRF = { "X-Requested-With": "toxic-express" };

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public details: unknown = null,
  ) {
    super(message);
  }
}

let refreshing: Promise<boolean> | null = null;

/** Single-flight refresh: concurrent 401s share one /auth/refresh call. */
export function refreshSession(): Promise<boolean> {
  refreshing ??= (async () => {
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "include",
        headers: CSRF,
      });
      if (!res.ok) {
        useAuth.getState().clear();
        return false;
      }
      useAuth.getState().setSession((await res.json()) as TokenOut);
      return true;
    } catch {
      return false;
    } finally {
      refreshing = null; // later 401s start a new refresh instead of reusing a settled one
    }
  })();
  return refreshing;
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  query?: Record<string, string | number | boolean | null | undefined>;
  signal?: AbortSignal;
  retryOn401?: boolean;
}

export async function api<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, query, signal, retryOn401 = true } = options;
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  for (const [key, value] of Object.entries(query ?? {})) {
    if (value !== undefined && value !== null && value !== "") url.searchParams.set(key, String(value));
  }
  const token = useAuth.getState().accessToken;
  const headers: Record<string, string> = { ...CSRF };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let res: Response;
  try {
    res = await fetch(url, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: "include",
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError(0, "network_error", "Can't reach Toxic-Express. Check your connection.");
  }

  if (res.status === 401 && token && retryOn401 && (await refreshSession())) {
    return api<T>(path, { ...options, retryOn401: false });
  }
  if (!res.ok) {
    let code = "http_error";
    let message = `Request failed (${res.status})`;
    let details: unknown = null;
    try {
      const data = (await res.json()) as { error?: { code: string; message: string; details: unknown } };
      if (data.error) ({ code, message, details } = data.error);
    } catch {
      /* non-JSON error body */
    }
    if (res.status === 429) message = "You're going a bit fast. Take a breath and try again shortly.";
    throw new ApiError(res.status, code, message, details);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "validation_error" && Array.isArray(err.details) && err.details[0]) {
      const first = err.details[0] as { loc: (string | number)[]; msg: string };
      const field = first.loc.filter((p) => p !== "body").join(".");
      return field ? `${field}: ${first.msg.replace(/^Value error, /, "")}` : first.msg;
    }
    return err.message;
  }
  return "Something went wrong. Please try again.";
}
