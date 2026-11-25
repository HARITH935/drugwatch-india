import type { BatchSearchResult } from "@/lib/backend";
import { Badge } from "@/components/ui/Badge";

import { FindingCard } from "./FindingCard";

const OUTCOME_LABEL = {
  FLAGGED: "Reported in a CDSCO alert",
  NOT_FOUND: "No matching alert found",
  NOT_SEARCHABLE: "This batch number can't be searched for",
} as const;

// "flagged"/"notFound" map directly to Badge's own non-red/green variants (globals.css); there
// is deliberately no third, reassuring colour for NOT_SEARCHABLE - it's a question about the
// input, not a result, so it gets the same neutral treatment as ordinary UI chrome.
const OUTCOME_VARIANT = {
  FLAGGED: "flagged",
  NOT_FOUND: "notFound",
  NOT_SEARCHABLE: "neutral",
} as const;

export function BatchResult({ result }: { result: BatchSearchResult }) {
  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">
          {result.drug} — batch {result.batch}
        </h1>
        <Badge variant={OUTCOME_VARIANT[result.outcome]}>{OUTCOME_LABEL[result.outcome]}</Badge>
        {/* The backend's own wording, rendered verbatim - never reworded or summarised here,
            so the one sentence CLAUDE.md §6 requires can't drift between this component and
            the API that is supposed to be the single source of it. */}
        <p>{result.meaning}</p>
      </header>

      {result.findings.length > 0 && (
        <section className="space-y-4">
          {result.findings.map((finding, index) => (
            // batchNumber + alertMonth + sourceUrl is unique per real finding, but two findings
            // for the same batch occasionally share an alert month (the spurious/non-spurious
            // pair is a real example) - the index breaks that tie without pretending the data
            // has an id it doesn't.
            <FindingCard
              key={`${finding.batchNumber}-${finding.alertMonth}-${index}`}
              finding={finding}
            />
          ))}
        </section>
      )}

      {result.sameBatchOtherMedicines.length > 0 && (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold">
            This exact batch number also appears under a different medicine name
          </h2>
          <p className="text-sm text-muted-foreground">
            CDSCO may have printed the name differently from what you typed - worth checking these
            too.
          </p>
          {result.sameBatchOtherMedicines.map((finding, index) => (
            <FindingCard
              key={`other-${finding.batchNumber}-${finding.alertMonth}-${index}`}
              finding={finding}
            />
          ))}
        </section>
      )}
    </div>
  );
}
