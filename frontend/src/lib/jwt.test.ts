import { describe, expect, it } from "vitest";

import { expiresAt, isExpired } from "@/lib/jwt";

// A real JWT has a signature too, but these functions never check one (see jwt.ts's own
// comment), so a fake token with the right shape - header.payload.signature, base64url JSON in
// the middle - is all a test needs.
function fakeToken(payload: Record<string, unknown>): string {
  const part = (value: unknown) => Buffer.from(JSON.stringify(value)).toString("base64url");
  return `${part({ alg: "HS256" })}.${part(payload)}.signature`;
}

describe("expiresAt", () => {
  it("reads the exp claim as epoch milliseconds", () => {
    expect(expiresAt(fakeToken({ exp: 1_000 }))).toBe(1_000_000);
  });

  it("returns null for a token with no exp claim", () => {
    expect(expiresAt(fakeToken({ sub: "a@example.com" }))).toBeNull();
  });

  it("returns null for something that isn't a three-part token", () => {
    expect(expiresAt("not-a-jwt")).toBeNull();
  });

  it("returns null for a payload that isn't valid JSON", () => {
    expect(expiresAt("header.not-json.signature")).toBeNull();
  });
});

describe("isExpired", () => {
  it("is false well before expiry", () => {
    const token = fakeToken({ exp: 1_000 }); // expires at 1_000_000ms
    expect(isExpired(token, 500_000)).toBe(false);
  });

  it("is true once past expiry", () => {
    const token = fakeToken({ exp: 1_000 });
    expect(isExpired(token, 1_000_001)).toBe(true);
  });

  it("is true inside the skew window, even though the token hasn't technically expired yet", () => {
    const token = fakeToken({ exp: 1_000 }); // expires at 1_000_000ms
    expect(isExpired(token, 995_000, 10_000)).toBe(true); // 5s left, 10s skew
  });

  it("is true for an unreadable token - treated as already expired, not as valid forever", () => {
    expect(isExpired("garbage")).toBe(true);
  });
});
