import { notFound } from "next/navigation";
import { connection } from "next/server";

import { DrugPageView } from "@/components/DrugPageView";
import { BackendError, getDrug } from "@/lib/backend";

export default async function DrugPage({ params }: PageProps<"/drugs/[id]">) {
  const { id } = await params;

  await connection(); // per-request: never cached in Next.js (ADR 0020) - Spring owns that cache
  let page = null;
  let error: BackendError | null = null;
  try {
    page = await getDrug(id);
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
          This medicine&apos;s page is unavailable right now. Please try again soon.
        </p>
      </main>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
      <DrugPageView page={page} />
    </main>
  );
}
