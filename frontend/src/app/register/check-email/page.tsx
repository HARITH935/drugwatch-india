import Link from "next/link";

// One message regardless of what actually happened server-side (AuthService.register's own
// anti-enumeration rule: whether that address already had an account is never revealed here).
export default function CheckEmailPage() {
  return (
    <main className="mx-auto w-full max-w-sm flex-1 space-y-4 px-4 py-10">
      <h1 className="text-2xl font-bold">Check your email</h1>
      <p>
        If that address can have an account, we&apos;ve sent it a link. Open it to confirm the
        address - the link works for 24 hours.
      </p>
      <Link href="/login" className="text-accent-foreground underline underline-offset-2">
        Back to log in
      </Link>
    </main>
  );
}
