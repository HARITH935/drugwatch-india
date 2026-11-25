import Link from "next/link";
import { connection } from "next/server";

import { DrugSearchForm } from "@/components/DrugSearchForm";
import { Badge } from "@/components/ui/Badge";
import { BackendError, searchDrugs } from "@/lib/backend";
import { batches } from "@/lib/format";

export default async function DrugSearchPage({ searchParams }: PageProps<"/drugs/search">) {
  const params = await searchParams;
  const q = firstValue(params.q);

  if (!q) {
    return (
      <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-10">
        <h1 className="text-2xl font-bold">Find a medicine</h1>
        <DrugSearchForm />
      </main>
    );
  }

  await connection(); // per-request: never cached in Next.js (ADR 0020) - Spring owns that cache
  let results;
  let error: BackendError | null = null;
  try {
    results = await searchDrugs(q);
  } catch (caught) {
    if (!(caught instanceof BackendError)) throw caught;
    error = caught;
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-10">
      <h1 className="text-2xl font-bold">Find a medicine</h1>
      <DrugSearchForm defaultValue={q} />

      {error && (
        <p role="status">
          {error.status === 400
            ? "Enter at least 3 characters to search."
            : "Search is unavailable right now. Please try again soon."}
        </p>
      )}

      {results && (
        <>
          <p className="text-sm text-muted-foreground">{results.note}</p>
          {results.matches.length === 0 ? (
            <p>No medicine name matched &ldquo;{q}&rdquo;.</p>
          ) : (
            <ul className="space-y-3">
              {results.matches.map((drug) => (
                <li key={drug.drugId} className="border-b border-border pb-3 last:border-0">
                  <Link
                    href={`/drugs/${drug.drugId}`}
                    className="font-medium text-accent-foreground underline underline-offset-2"
                  >
                    {drug.productName}
                  </Link>
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-sm text-muted-foreground">
                    <span>{batches(drug.findings)} reported</span>
                    {drug.drugClasses.map((drugClass) => (
                      <Badge key={drugClass} variant="neutral">
                        {drugClass}
                      </Badge>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </main>
  );
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}
