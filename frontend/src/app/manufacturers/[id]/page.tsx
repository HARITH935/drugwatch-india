import { notFound } from "next/navigation";
import { connection } from "next/server";
import { Suspense } from "react";

import { ManufacturerPageView } from "@/components/ManufacturerPageView";
import { RiskScoreCard } from "@/components/RiskScoreCard";
import { BackendError, getManufacturer, getRiskScore } from "@/lib/backend";

export default async function ManufacturerPageRoute({ params }: PageProps<"/manufacturers/[id]">) {
  const { id } = await params;

  await connection(); // per-request: never cached in Next.js (ADR 0020) - Spring owns that cache
  let page = null;
  let error: BackendError | null = null;
  try {
    page = await getManufacturer(id);
  } catch (caught) {
    if (!(caught instanceof BackendError)) throw caught;
    error = caught;
  }

  if (error?.status === 404) {
    notFound();
  }
  if (error || page === null) {
    if (error) console.error(error.message);
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
        <p role="status">
          This company&apos;s page is unavailable right now. Please try again soon.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-6 px-4 py-10">
      <ManufacturerPageView page={page} />
      {/* Its own Suspense boundary, fetched separately from the data above: the risk model is
          a second, slower, independently-failing service (ADR 0017), and the backend's own
          RiskController promises "everything else on this page ... is unaffected" by it being
          down - a slow or dead model must not hold up what's already here. */}
      <Suspense fallback={<p role="status">Loading the risk score…</p>}>
        <RiskSection manufacturerId={id} />
      </Suspense>
    </main>
  );
}

async function RiskSection({ manufacturerId }: { manufacturerId: string }) {
  let risk = null;
  try {
    risk = await getRiskScore(manufacturerId);
  } catch (caught) {
    if (!(caught instanceof BackendError)) throw caught;
    console.error(caught.message);
  }
  if (risk === null) {
    return <p role="status">The risk score is unavailable right now.</p>;
  }
  return <RiskScoreCard result={risk} />;
}
