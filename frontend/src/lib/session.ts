import "server-only";

import { cookies } from "next/headers";

import { type AuthTokens, refreshSession } from "@/lib/backend";
import { isExpired } from "@/lib/jwt";

// Decision B (ADR 0020): the browser gets httpOnly cookies, never the tokens themselves. Two
// cookies, not one object, because they expire on different schedules (15 min vs 30 days -
// AccessTokens.LIFETIME and AuthService.REFRESH_LIFETIME) and only the refresh token needs to
// survive a browser restart.
const ACCESS_COOKIE = "access_token";
const REFRESH_COOKIE = "refresh_token";
const REFRESH_MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

// Next.js refuses a non-secure cookie over plain http, which is what this site runs on until
// Phase 12's TLS - so `secure` can only be true once the site is actually served over https.
const isProduction = process.env.NODE_ENV === "production";

const COOKIE_OPTIONS = {
  httpOnly: true,
  secure: isProduction,
  sameSite: "lax" as const,
  path: "/",
};

// Next.js only allows cookies().set()/delete() inside a Server Action or Route Handler - never
// inside a plain Server Component's render. Every export below that mutates cookies must only be
// called from one of those two places.

export async function setSessionCookies(tokens: AuthTokens): Promise<void> {
  const store = await cookies();
  store.set(ACCESS_COOKIE, tokens.accessToken, {
    ...COOKIE_OPTIONS,
    maxAge: tokens.expiresInSeconds,
  });
  store.set(REFRESH_COOKIE, tokens.refreshToken, {
    ...COOKIE_OPTIONS,
    maxAge: REFRESH_MAX_AGE_SECONDS,
  });
}

export async function clearSessionCookies(): Promise<void> {
  const store = await cookies();
  store.delete(ACCESS_COOKIE);
  store.delete(REFRESH_COOKIE);
}

export async function getRefreshToken(): Promise<string | null> {
  const store = await cookies();
  return store.get(REFRESH_COOKIE)?.value ?? null;
}

/**
 * A valid access token to attach as `Authorization: Bearer <token>`, refreshing it first if it's
 * expired or close to it. Only callable from a Server Action or Route Handler (see above) - it
 * is the one place this project calls AuthService.refresh() for real, as opposed to on login.
 *
 * Returns null when there's no session, or the refresh token has already been used or revoked
 * (AuthService's reuse-detection revokes every session for the account) - the caller should treat
 * that the same as never having been logged in.
 */
export async function getAccessToken(): Promise<string | null> {
  const store = await cookies();
  const access = store.get(ACCESS_COOKIE)?.value;
  if (access && !isExpired(access)) return access;

  const refresh = store.get(REFRESH_COOKIE)?.value;
  if (!refresh) return null;

  try {
    const tokens = await refreshSession(refresh);
    await setSessionCookies(tokens);
    return tokens.accessToken;
  } catch {
    await clearSessionCookies();
    return null;
  }
}

/**
 * Cheap, cookie-presence-only check for deciding what the header shows - safe to call from a
 * plain Server Component (no cookie mutation, no network call). It is not an authorization
 * check: a revoked refresh token still passes this until something actually tries to use it.
 */
export async function hasSession(): Promise<boolean> {
  const store = await cookies();
  return store.get(REFRESH_COOKIE) !== undefined;
}
