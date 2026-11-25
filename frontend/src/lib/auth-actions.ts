"use server";

import { redirect } from "next/navigation";

import { BackendError, loginAccount, logoutSession, registerAccount } from "@/lib/backend";
import { clearSessionCookies, getRefreshToken, setSessionCookies } from "@/lib/session";

// Plain <form action={...}> Server Actions, not client-side handlers - the same "no JavaScript
// we wrote ourselves" approach as the GET search forms, just POST instead of GET because these
// mutate (and because a password doesn't belong in a URL's query string or server access log).

/** Redirects to `${path}?error=<kind>`, distinguishing "you did something wrong" from "we're
 * having trouble right now" without saying which field or which outcome (anti-enumeration). */
function redirectOnError(path: string, error: unknown): never {
  if (error instanceof BackendError) {
    const kind = error.status === 400 || error.status === 401 ? "invalid" : "unavailable";
    redirect(`${path}?error=${kind}`);
  }
  throw error;
}

export async function registerAction(formData: FormData): Promise<void> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  try {
    await registerAccount(email, password);
  } catch (error) {
    redirectOnError("/register", error);
  }
  // The same destination whichever happened server-side (AuthService.register's own rule):
  // the only thing the caller can learn is that a request was made.
  redirect("/register/check-email");
}

export async function loginAction(formData: FormData): Promise<void> {
  const email = String(formData.get("email") ?? "");
  const password = String(formData.get("password") ?? "");

  let tokens;
  try {
    tokens = await loginAccount(email, password);
  } catch (error) {
    redirectOnError("/login", error);
  }
  await setSessionCookies(tokens);
  redirect("/");
}

export async function logoutAction(): Promise<void> {
  const refreshToken = await getRefreshToken();
  if (refreshToken) {
    // Best-effort: whether or not Spring manages to revoke it, clearing the cookies below is
    // what actually ends the session from this browser's point of view.
    await logoutSession(refreshToken).catch(() => {});
  }
  await clearSessionCookies();
  redirect("/");
}
