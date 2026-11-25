// Reading an access token's own claims, without checking its signature. That's fine here: this
// is only ever used to decide "does this look worth sending" before a proxied call - Spring's
// NimbusJwtDecoder verifies the real signature on every request and rejects a forged or expired
// token regardless of what this says. Never use this result to grant anything by itself.

// AccessTokens.issue() puts the user's id in `sub` and the email in its own `email` claim -
// confirmed against a real token; only `exp` is actually read below.
type AccessTokenPayload = {
  exp?: number; // seconds since epoch, per the JWT spec
};

function decodePayload(token: string): AccessTokenPayload | null {
  const parts = token.split(".");
  if (parts.length !== 3) return null;
  try {
    const json = Buffer.from(parts[1], "base64url").toString("utf8");
    return JSON.parse(json) as AccessTokenPayload;
  } catch {
    return null;
  }
}

/** Epoch milliseconds the token claims to expire at, or null if it can't be read at all. */
export function expiresAt(token: string): number | null {
  const payload = decodePayload(token);
  if (!payload?.exp) return null;
  return payload.exp * 1000;
}

/**
 * True once the token is expired, or within `skewMs` of it - refreshing a few seconds early
 * costs nothing and avoids a request landing at Spring just as the token stops being valid.
 */
export function isExpired(token: string, now = Date.now(), skewMs = 10_000): boolean {
  const exp = expiresAt(token);
  return exp === null || exp <= now + skewMs;
}
