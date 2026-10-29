import { afterEach, describe, expect, it, vi } from "vitest";

import { useAuth } from "@/store/auth";

import { api, ApiError, refreshSession } from "./api";
import { cn } from "./utils";

const tokens = (token: string) => ({
  access_token: token,
  token_type: "bearer",
  expires_in: 900,
  user: { id: "u1", handle: "rae" },
});

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

afterEach(() => {
  vi.restoreAllMocks();
  useAuth.getState().clear();
});

describe("api client", () => {
  it("shares one refresh between concurrent callers", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => respond(200, tokens("t1")));
    const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
    expect(results).toEqual([true, true, true]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(useAuth.getState().accessToken).toBe("t1");
  });

  it("refreshes once on 401 and retries the request with the new token", async () => {
    useAuth.getState().setSession(tokens("expired") as never);
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
      const url = String(input);
      if (url.endsWith("/auth/refresh")) return respond(200, tokens("fresh"));
      const auth = (init?.headers as Record<string, string>).Authorization;
      return auth === "Bearer fresh" ? respond(200, { ok: true }) : respond(401, { error: { code: "unauthorized", message: "expired" } });
    });
    await expect(api("/me")).resolves.toEqual({ ok: true });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("clears the session when refresh fails and surfaces API errors", async () => {
    useAuth.getState().setSession(tokens("old") as never);
    vi.spyOn(globalThis, "fetch").mockImplementation(() => respond(401, { error: { code: "unauthorized", message: "nope" } }));
    await expect(api("/me")).rejects.toBeInstanceOf(ApiError);
    expect(useAuth.getState().status).toBe("anonymous");
  });

  it("sends the CSRF header on every request", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(() => respond(200, {}));
    await api("/meta");
    expect((fetchMock.mock.calls[0]![1]!.headers as Record<string, string>)["X-Requested-With"]).toBe("toxic-express");
  });
});

describe("cn", () => {
  it("keeps colour and DESIGN.md font-size utilities side by side", () => {
    expect(cn("text-ink-dark", "text-link-sm")).toBe("text-ink-dark text-link-sm");
    expect(cn("text-link", "text-link-lg")).toBe("text-link-lg");
    expect(cn("rounded-sm", "rounded-lg")).toBe("rounded-lg");
  });
});
