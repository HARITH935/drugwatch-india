// CLAUDE.md §6: "Disclaimer on every page". The text is the same string the backend sends
// (PublicNotes.DISCLAIMER); Disclaimer.test.tsx fails if this copy drifts from the rule.
export const DISCLAIMER = "Not medical advice. Data from CDSCO public alerts.";

export function Disclaimer() {
  return <p className="text-sm text-muted-foreground">{DISCLAIMER}</p>;
}
