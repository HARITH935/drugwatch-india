import Link from "next/link";
import { connection } from "next/server";

import { BackendError, verifyEmailToken } from "@/lib/backend";

export default async function VerifyPage({ searchParams }: PageProps<"/verify">) {
  const params = await searchParams;
  const token = firstValue(params.token);

  if (!token) {
    return (
      <Prompt title="Nothing to verify">
        <p>This page needs the link from your email, not a bare visit.</p>
      </Prompt>
    );
  }

  await connection(); // per-request: never cached in Next.js (ADR 0020)
  let failed = false;
  try {
    await verifyEmailToken(token);
  } catch (error) {
    if (!(error instanceof BackendError)) throw error;
    failed = true;
  }

  if (failed) {
    return (
      <Prompt title="That link didn't work">
        <p>
          It may have already been used, or it&apos;s more than 24 hours old. Register again to get
          a new one.
        </p>
      </Prompt>
    );
  }

  return (
    <Prompt title="Email confirmed">
      <p>Your address is confirmed. You can log in now.</p>
      <Link href="/login" className="text-accent-foreground underline underline-offset-2">
        Log in
      </Link>
    </Prompt>
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
