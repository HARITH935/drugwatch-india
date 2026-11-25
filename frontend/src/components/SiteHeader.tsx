import Link from "next/link";

// Minimal on purpose at step 1: real navigation (drug/manufacturer/watchlist links, the auth
// state) arrives with the pages that need it, steps 2-6. This exists now so every later page
// inherits the same header rather than each one inventing its own.
export function SiteHeader() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-16 max-w-3xl items-center px-4">
        <Link href="/" className="text-lg font-semibold text-foreground">
          DrugWatch India
        </Link>
      </div>
    </header>
  );
}
