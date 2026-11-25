import Link from "next/link";

// Watchlist/auth-state links arrive with the pages that need them (steps 4-6). This exists now
// so every later page inherits the same header rather than each one inventing its own.
export function SiteHeader() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex h-16 max-w-3xl items-center justify-between px-4">
        <Link href="/" className="text-lg font-semibold text-foreground">
          DrugWatch India
        </Link>
        <Link
          href="/drugs/search"
          className="text-sm text-accent-foreground underline underline-offset-2"
        >
          Find a medicine
        </Link>
      </div>
    </header>
  );
}
