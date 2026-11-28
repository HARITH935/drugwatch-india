import { describe, expect, it } from "vitest";

/**
 * The pre-launch lock's behaviour (Phase 12 step 5).
 *
 * Worth pinning rather than eyeballing: this is the only thing standing between CDSCO data and
 * anybody who finds the URL before permission is recorded (CLAUDE.md §7), and the two ways it
 * could fail are both silent. Letting everyone in looks exactly like a working site; letting
 * nobody in looks exactly like a broken deploy.
 *
 * `isAuthorised` reads the password when the module is first imported, so each case re-imports
 * with its own environment rather than mutating a shared one.
 */

async function freshIsAuthorised(env: Record<string, string | undefined>) {
  const previous = { ...process.env };
  for (const [key, value] of Object.entries(env)) {
    if (value === undefined) delete process.env[key];
    else process.env[key] = value;
  }
  // A fresh module registry, so the constants above are evaluated against this environment.
  const { resetModules } = await import("vitest").then((m) => ({
    resetModules: m.vi.resetModules,
  }));
  resetModules();
  const loaded = await import("./proxy");
  process.env = previous;
  return loaded.isAuthorised;
}

const basic = (user: string, password: string) => `Basic ${btoa(`${user}:${password}`)}`;

describe("the pre-launch password lock", () => {
  it("lets everyone through when no password is configured", async () => {
    // This is launch day, and also local dev and CI: without it the e2e suite would 401 on
    // every page.
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: undefined });

    expect(isAuthorised(null)).toBe(true);
  });

  it("refuses a request with no credentials once a password is set", async () => {
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: "open-sesame" });

    expect(isAuthorised(null)).toBe(false);
  });

  it("accepts the configured username and password", async () => {
    const isAuthorised = await freshIsAuthorised({
      SITE_PASSWORD: "open-sesame",
      SITE_USERNAME: "reviewer",
    });

    expect(isAuthorised(basic("reviewer", "open-sesame"))).toBe(true);
  });

  it("refuses the right password under the wrong username", async () => {
    const isAuthorised = await freshIsAuthorised({
      SITE_PASSWORD: "open-sesame",
      SITE_USERNAME: "reviewer",
    });

    expect(isAuthorised(basic("someone-else", "open-sesame"))).toBe(false);
  });

  it("refuses a wrong password", async () => {
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: "open-sesame" });

    expect(isAuthorised(basic("drugwatch", "guess"))).toBe(false);
  });

  it("refuses a password that is merely a prefix of the real one", async () => {
    // The case a length check alone would wave through.
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: "open-sesame" });

    expect(isAuthorised(basic("drugwatch", "open"))).toBe(false);
  });

  it("refuses the password with a trailing NUL appended", async () => {
    // The case the length check actually earns its place on, found by deleting that check and
    // watching every other test still pass. Out-of-range charCodeAt gives NaN, which coerces to 0
    // in the XOR, so comparing "pw" against "pw\0" would otherwise come out equal and accept a
    // guess that is not the password.
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: "open-sesame" });

    expect(isAuthorised(basic("drugwatch", "open-sesame\u0000"))).toBe(false);
  });

  it("keeps a password that contains colons intact", async () => {
    // Basic auth joins user and password with a colon, so splitting on the last one - or on all
    // of them - would corrupt a generated password that happens to contain one.
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: "a:b:c" });

    expect(isAuthorised(basic("drugwatch", "a:b:c"))).toBe(true);
  });

  it("refuses a malformed header rather than throwing", async () => {
    const isAuthorised = await freshIsAuthorised({ SITE_PASSWORD: "open-sesame" });

    expect(isAuthorised("Basic not-valid-base64!!")).toBe(false);
    expect(isAuthorised("Bearer open-sesame")).toBe(false);
    expect(isAuthorised(`Basic ${btoa("no-colon-here")}`)).toBe(false);
  });
});
