import { describe, expect, it } from "vitest";

import { safeNext } from "./AuthPages";

describe("safeNext (open-redirect guard)", () => {
  it.each([
    [null, "/"],
    ["/p/123", "/p/123"],
    ["//evil.com", "/"],
    ["https://evil.com", "/"],
    ["javascript:alert(1)", "/"],
  ])("%s -> %s", (input, expected) => {
    expect(safeNext(input)).toBe(expected);
  });
});
