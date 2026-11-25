import type { ReactNode } from "react";

// Only three status variants exist on purpose - this is the component CLAUDE.md §6 is enforced
// through. "flagged" and "notFound" are deliberately not red/green: see globals.css's token
// comments. There is no "success"/"safe" variant at all - it would have nothing true to label.
type Variant = "flagged" | "notFound" | "error" | "neutral";

const VARIANT_CLASSES: Record<Variant, string> = {
  flagged: "bg-flagged-bg text-flagged-foreground",
  notFound: "bg-not-found-bg text-not-found-foreground",
  error: "bg-error-bg text-error-foreground",
  neutral: "bg-background text-muted-foreground border border-border",
};

export function Badge({ variant, children }: { variant: Variant; children: ReactNode }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${VARIANT_CLASSES[variant]}`}
    >
      {children}
    </span>
  );
}
