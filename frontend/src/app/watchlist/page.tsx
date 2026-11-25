import Link from "next/link";
import { connection } from "next/server";

import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import {
  BackendError,
  getNotificationHistory,
  getWatchlist,
  type NotificationHistory,
  type WatchlistResult,
} from "@/lib/backend";
import { batches, formatAlertMonth, formatDate } from "@/lib/format";
import { getAccessTokenIfFresh } from "@/lib/session";
import { addWatchAction, removeWatchAction } from "@/lib/watchlist-actions";

export default async function WatchlistPage({ searchParams }: PageProps<"/watchlist">) {
  const params = await searchParams;
  const error = firstValue(params.error);

  // Read-only - never refreshes (see session.ts's own comment on why) - so a session idle for
  // more than 15 minutes shows this instead of silently working. Adding or removing a watch
  // below goes through a Server Action, which refreshes it transparently.
  const token = await getAccessTokenIfFresh();
  if (!token) {
    return (
      <Prompt title="Your watchlist">
        <p>Log in to see the medicines you&apos;re watching.</p>
        <Link href="/login" className="text-accent-foreground underline underline-offset-2">
          Log in
        </Link>
      </Prompt>
    );
  }

  await connection(); // per-request: never cached in Next.js (ADR 0020)
  let watchlist: WatchlistResult | null = null;
  let history: NotificationHistory | null = null;
  let failed = false;
  try {
    [watchlist, history] = await Promise.all([getWatchlist(token), getNotificationHistory(token)]);
  } catch (caught) {
    if (!(caught instanceof BackendError)) throw caught;
    failed = true;
  }

  if (failed || !watchlist || !history) {
    return (
      <Prompt title="Your watchlist">
        <p role="status">The watchlist is unavailable right now. Please try again soon.</p>
      </Prompt>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-10 px-4 py-10">
      <section className="space-y-4">
        <h1 className="text-2xl font-bold">Your watchlist</h1>
        <p className="text-sm text-muted-foreground">{watchlist.note}</p>

        {error && <p role="status">{error}</p>}

        <form action={addWatchAction} className="flex flex-col gap-2 sm:flex-row">
          <Input
            name="term"
            required
            minLength={3}
            maxLength={100}
            placeholder="e.g. Paracetamol"
            aria-label="Medicine or manufacturer name to watch"
            className="sm:flex-1"
          />
          <Button type="submit">Watch</Button>
        </form>

        {watchlist.watches.length === 0 ? (
          <p>You aren&apos;t watching anything yet.</p>
        ) : (
          <ul className="space-y-3">
            {watchlist.watches.map((watch) => (
              <li key={watch.id}>
                <Card className="flex items-center justify-between gap-4">
                  <div>
                    <p className="font-medium">{watch.term}</p>
                    <p className="text-sm text-muted-foreground">
                      Watching since {formatDate(watch.createdAt)}
                    </p>
                  </div>
                  <form action={removeWatchAction}>
                    <input type="hidden" name="id" value={watch.id} />
                    <Button type="submit" variant="outline" size="sm">
                      Stop watching
                    </Button>
                  </form>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-4">
        <h2 className="text-xl font-bold">Notifications sent to you</h2>
        <p className="text-sm text-muted-foreground">{history.note}</p>
        {history.notifications.length === 0 ? (
          <p>
            Nothing yet - you&apos;ll see an alert month here once one matches something you watch.
          </p>
        ) : (
          <ul className="space-y-2">
            {history.notifications.map((notification, index) => (
              <li
                key={`${notification.term}-${notification.alertMonth}-${index}`}
                className="border-b border-border pb-2 last:border-0"
              >
                <Link
                  href={`/drugs/search?q=${encodeURIComponent(notification.term)}`}
                  className="font-medium text-accent-foreground underline underline-offset-2"
                >
                  {notification.term}
                </Link>{" "}
                - {batches(notification.findingsMatched)} in the{" "}
                {formatAlertMonth(notification.alertMonth)} alert, sent{" "}
                {formatDate(notification.sentAt)}
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function Prompt({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto w-full max-w-sm flex-1 space-y-4 px-4 py-10">
      <h1 className="text-2xl font-bold">{title}</h1>
      {children}
    </main>
  );
}
