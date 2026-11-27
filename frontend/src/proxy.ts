import { type NextRequest, NextResponse } from "next/server";

/**
 * The pre-launch password lock (Phase 12 step 5, ADR 0021).
 *
 * CLAUDE.md §7 is the reason this exists: CDSCO's data may not be published until permission is
 * recorded in docs/permissions.md. Until then the site has to be deployable and reviewable -
 * Playwright runs against it, Harith can show it to people - without being readable by anyone who
 * finds the URL. Vercel's own password protection is a paid feature, so the gate is here.
 *
 * **Switched by one variable, and off by default.** No `SITE_PASSWORD` means no lock, which is
 * what local dev and CI get (the e2e suite would otherwise 401 on every page), and it is also what
 * launch looks like: unset the variable, redeploy, and the site is public. There is no second
 * place to remember.
 *
 * HTTP Basic rather than a login page on purpose: it needs no cookie, no session, no state and no
 * UI, so it cannot interact with the site's real authentication (ADR 0020's httpOnly session
 * cookies) or leave a half-logged-in state behind when the lock is lifted.
 */

const USERNAME = process.env.SITE_USERNAME ?? "drugwatch";
const PASSWORD = process.env.SITE_PASSWORD ?? "";

/**
 * Compare without leaking the answer through timing. `===` on strings returns as soon as two
 * characters differ, so the time it takes reveals how much of a guess was right - enough, over
 * many tries, to recover a secret one character at a time. This always reads both strings fully.
 *
 * Hand-written because `crypto.timingSafeEqual` is Node-only and this runs on Vercel's edge
 * runtime, where `Buffer` does not exist.
 */
function equalsInConstantTime(a: string, b: string): boolean {
  // The lengths themselves are not secret, but bail on a mismatch only after the loop so that a
  // wrong-length guess is not measurably faster than a wrong-content one.
  let mismatch = a.length === b.length ? 0 : 1;
  const length = Math.max(a.length, b.length);
  for (let index = 0; index < length; index += 1) {
    mismatch |= a.charCodeAt(index) ^ b.charCodeAt(index);
  }
  return mismatch === 0;
}

export function isAuthorised(header: string | null): boolean {
  if (!PASSWORD) return true; // no lock configured: the site is public
  if (!header?.startsWith("Basic ")) return false;

  let decoded: string;
  try {
    // atob, not Buffer: see equalsInConstantTime's note about the edge runtime.
    decoded = atob(header.slice("Basic ".length));
  } catch {
    return false; // not valid base64 - a malformed header, not a wrong password
  }

  // Split on the FIRST colon only: a password may legitimately contain colons.
  const separator = decoded.indexOf(":");
  if (separator === -1) return false;
  const user = decoded.slice(0, separator);
  const password = decoded.slice(separator + 1);

  // Both are checked, and `&` rather than `&&` so a wrong username does not skip the password
  // comparison and answer faster than a wrong password would.
  const userOk = equalsInConstantTime(user, USERNAME);
  const passwordOk = equalsInConstantTime(password, PASSWORD);
  return userOk && passwordOk;
}

export function proxy(request: NextRequest) {
  if (isAuthorised(request.headers.get("authorization"))) {
    return NextResponse.next();
  }
  return new NextResponse("This site is not public yet.", {
    status: 401,
    headers: {
      // Without this the browser shows a bare error instead of asking for a password.
      "WWW-Authenticate": 'Basic realm="DrugWatch India (pre-launch)", charset="UTF-8"',
      // A locked page must never be cached, by the browser or by Vercel's edge: a cached 401
      // would outlive the lock, and a cached page would outlive the lock being put back.
      "Cache-Control": "no-store",
    },
  });
}

export const proxyConfig = {
  // Everything, including static assets and the API routes the site calls itself. A lock with
  // holes in it is not a lock - and once the browser has authenticated it sends the header with
  // every request anyway, so covering assets costs nothing.
  matcher: ["/:path*"],
};
