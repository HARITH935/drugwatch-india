import { connection } from "next/server";

import { DashboardEmbed } from "@/components/DashboardEmbed";
import { BackendError, getDashboardKeys } from "@/lib/backend";

export default async function DashboardsPage() {
  await connection(); // per-request: never cached in Next.js (ADR 0020)
  let keys: string[] = [];
  let failed = false;
  try {
    keys = (await getDashboardKeys()).dashboards;
  } catch (caught) {
    if (!(caught instanceof BackendError)) throw caught;
    failed = true;
  }

  return (
    <main className="mx-auto w-full max-w-5xl flex-1 space-y-6 px-4 py-10">
      <h1 className="text-2xl font-bold">Dashboards</h1>
      <p className="text-sm text-muted-foreground">
        Charts built from the same CDSCO alerts the rest of this site uses.
      </p>

      {failed || keys.length === 0 ? (
        <p role="status">Dashboards are unavailable right now. Please try again soon.</p>
      ) : (
        <DashboardEmbed keys={keys} />
      )}
    </main>
  );
}
