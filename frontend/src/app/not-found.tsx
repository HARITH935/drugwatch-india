import Link from "next/link";

// Rendered for any route Next.js can't match, and whenever a page calls notFound() - here, a
// drug or manufacturer id the backend's NotFoundException rejected. The disclaimer still shows:
// layout.tsx's footer wraps this page the same as every other one.
export default function NotFound() {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 space-y-4 px-4 py-10">
      <h1 className="text-2xl font-bold">Not found</h1>
      <p>There&apos;s nothing at this address.</p>
      <Link href="/" className="text-accent-foreground underline underline-offset-2">
        Back to search
      </Link>
    </main>
  );
}
