import Link from "next/link";

import { Button } from "@/components/ui/Button";
import { logoutAction } from "@/lib/auth-actions";
import { hasSession } from "@/lib/session";

// hasSession() only reads a cookie - cheap enough to call on every page's header without
// turning this into a network round trip.
export async function SiteHeader() {
  const loggedIn = await hasSession();

  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex min-h-16 max-w-3xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-4 py-3">
        <Link href="/" className="text-lg font-semibold text-foreground">
          DrugWatch India
        </Link>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <Link
            href="/drugs/search"
            className="text-accent-foreground underline underline-offset-2"
          >
            Find a medicine
          </Link>
          <Link href="/dashboards" className="text-accent-foreground underline underline-offset-2">
            Dashboards
          </Link>
          {loggedIn ? (
            <>
              <Link
                href="/watchlist"
                className="text-accent-foreground underline underline-offset-2"
              >
                Watchlist
              </Link>
              <form action={logoutAction}>
                <Button type="submit" variant="ghost" size="sm">
                  Log out
                </Button>
              </form>
            </>
          ) : (
            <>
              <Link href="/login" className="text-accent-foreground underline underline-offset-2">
                Log in
              </Link>
              <Link
                href="/register"
                className="text-accent-foreground underline underline-offset-2"
              >
                Register
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
