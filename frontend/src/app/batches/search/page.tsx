import Link from "next/link";
import { connection } from "next/server";

import { BatchResult } from "@/components/BatchResult";
import { BackendError, searchBatch, type BatchSearchResult } from "@/lib/backend";
import { fieldLabel } from "@/lib/format";

export default async function BatchSearchResultPage({
  searchParams,
}: PageProps<"/batches/search">) {
  const params = await searchParams;
  const drug = firstValue(params.drug);
  const batch = firstValue(params.batch);

  if (!drug || !batch) {
    return (
      <Prompt>
        <p>Enter a medicine name and a batch number to check whether it was reported.</p>
        <Link href="/" className="text-accent-foreground underline underline-offset-2">
          Back to search
        </Link>
      </Prompt>
    );
  }

  await connection(); // per-request: never cached in Next.js (ADR 0020) - Spring owns that cache
  // Only the fetch is inside the try (React's error-boundaries lint rule: JSX built inside a
  // try/catch is not actually caught by it, because rendering happens later, not at the call).
  let result: BatchSearchResult | null = null;
  let error: BackendError | null = null;
  try {
    result = await searchBatch(drug, batch);
  } catch (caught) {
    if (!(caught instanceof BackendError)) throw caught;
    error = caught;
  }

  if (error?.status === 400 && error.problem) {
    const messages = Object.entries(error.problem.detail);
    return (
      <Prompt>
        <p>That search can&apos;t be run as entered:</p>
        <ul className="list-disc space-y-1 pl-6">
          {messages.map(([field, message]) => (
            <li key={field}>
              {fieldLabel(field)}: {message}
            </li>
          ))}
        </ul>
        <Link href="/" className="text-accent-foreground underline underline-offset-2">
          Try again
        </Link>
      </Prompt>
    );
  }

  if (error || result === null) {
    if (error) console.error(error.message);
    return (
      <Prompt>
        <p role="status">The batch checker is unavailable right now. Please try again soon.</p>
      </Prompt>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
      <BatchResult result={result} />
    </main>
  );
}

function firstValue(value: string | string[] | undefined): string | undefined {
  return Array.isArray(value) ? value[0] : value;
}

function Prompt({ children }: { children: React.ReactNode }) {
  return <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-10">{children}</main>;
}
