"use server";

import { redirect } from "next/navigation";

import { addWatch, BackendError, removeWatch } from "@/lib/backend";
import { getAccessToken } from "@/lib/session";

// A Server Action, unlike the watchlist page itself, is an allowed place to refresh the session
// (session.ts's getAccessToken() may write cookies here) - so adding or removing a watch quietly
// extends a session that a plain page visit wouldn't.

export async function addWatchAction(formData: FormData): Promise<void> {
  const token = await getAccessToken();
  if (!token) redirect("/login");

  const term = String(formData.get("term") ?? "");
  try {
    await addWatch(term, token);
  } catch (error) {
    // The backend's own message is shown as-is (e.g. "You are already watching that.") - unlike
    // auth's errors, there's no anti-enumeration reason to blur these.
    if (error instanceof BackendError && error.problem?.error) {
      redirect(`/watchlist?error=${encodeURIComponent(error.problem.error)}`);
    }
    throw error;
  }
  redirect("/watchlist");
}

export async function removeWatchAction(formData: FormData): Promise<void> {
  const token = await getAccessToken();
  if (!token) redirect("/login");

  const id = Number(formData.get("id"));
  try {
    await removeWatch(id, token);
  } catch (error) {
    // A 404 here just means it's already gone (a double submit, another tab) - nothing to tell
    // the visitor that the redirect below doesn't already show.
    if (!(error instanceof BackendError)) throw error;
  }
  redirect("/watchlist");
}
