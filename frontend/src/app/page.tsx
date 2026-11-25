import { connection } from "next/server";
import { Suspense } from "react";

import { LatestAlertsSummary } from "@/components/LatestAlertsSummary";
import { BackendError, backendGet, type LatestAlerts as LatestAlertsData } from "@/lib/backend";

export default function Home() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-8 px-4 py-10">
      {/* Static: prerendered at build time, shown instantly. */}
      <header className="space-y-2">
        <h1 className="text-3xl font-bold">DrugWatch India</h1>
        <p>
          Check whether a medicine batch appears in the Central Drugs Standard Control
          Organisation&apos;s published &ldquo;Not of Standard Quality&rdquo; alerts.
        </p>
      </header>

      {/* Dynamic: fetched per request, streamed in when ready. */}
      <Suspense fallback={<p role="status">Loading the latest alerts…</p>}>
        <LatestAlerts />
      </Suspense>
    </main>
  );
}

async function LatestAlerts() {
  // Request time, never build time. Spring already caches this in Redis keyed by the data's
  // alert month (Phase 9 step 6), so a monthly load invalidates it by itself. A second,
  // time-based cache here could keep showing last month's alerts after a new month arrives -
  // the exact failure Phase 9's CacheConfig was designed to make impossible.
  await connection();
  // Only the fetch is inside the try. A try/catch around returned JSX looks as if it catches
  // rendering errors in that JSX, and it can't - React's lint rule says so, and it's right.
  let data: LatestAlertsData | null = null;
  try {
    data = await backendGet<LatestAlertsData>("/api/v1/alerts/latest");
  } catch (error) {
    if (!(error instanceof BackendError)) throw error; // anything else is a real bug: let it surface
    console.error(error.message);
  }
  if (data === null) {
    return (
      <p role="status">The latest alert summary is unavailable right now. Please try again soon.</p>
    );
  }
  return <LatestAlertsSummary data={data} />;
}
