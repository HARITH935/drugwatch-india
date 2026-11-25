import Link from "next/link";

import type { Finding } from "@/lib/backend";
import { formatAlertMonth } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { Card } from "@/components/ui/Card";

// CLAUDE.md §6, three things every finding must show: the batch number, the source alert month,
// and a link to the original CDSCO document. All three are rendered unconditionally below - not
// behind an "if present" check - because Finding.java's own constructor guarantees they exist.
export function FindingCard({ finding }: { finding: Finding }) {
  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        {/* whitespace-pre-line: CDSCO sometimes prints a name across several lines, and that
            line-wrapping is part of what was actually printed, not an artefact to collapse. */}
        <p className="whitespace-pre-line font-semibold">{finding.productName}</p>
        {finding.spurious && <Badge variant="flagged">Reported as spurious (counterfeit)</Badge>}
      </div>

      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Batch</dt>
        <dd>{finding.batchNumber}</dd>

        <dt className="text-muted-foreground">Alert month</dt>
        <dd>{formatAlertMonth(finding.alertMonth)}</dd>

        {finding.failureReason && (
          <>
            <dt className="text-muted-foreground">Reason</dt>
            <dd className="whitespace-pre-line">{finding.failureReason}</dd>
          </>
        )}

        {/* Never a manufacturer name on a spurious row - that company is the counterfeit's
            victim, not its maker (the real maker is unknown; CLAUDE.md §6). */}
        {finding.spurious ? (
          finding.nameOnPack && (
            <>
              <dt className="text-muted-foreground">Name printed on the pack</dt>
              <dd>{finding.nameOnPack}</dd>
            </>
          )
        ) : (
          <>
            <dt className="text-muted-foreground">Manufacturer</dt>
            <dd>
              {finding.manufacturerId && finding.manufacturerName ? (
                <Link
                  href={`/manufacturers/${finding.manufacturerId}`}
                  className="text-accent-foreground underline underline-offset-2"
                >
                  {finding.manufacturerName}
                </Link>
              ) : (
                (finding.manufacturerName ?? "Not stated in the alert")
              )}
            </dd>
          </>
        )}

        {finding.reportedBy && (
          <>
            <dt className="text-muted-foreground">Tested by</dt>
            <dd>
              {finding.reportedBy}
              {finding.labType && ` (${finding.labType.toLowerCase()} lab)`}
            </dd>
          </>
        )}
      </dl>

      {finding.failureCategories.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {finding.failureCategories.map((category) => (
            <Badge key={category} variant="neutral">
              {category}
            </Badge>
          ))}
        </div>
      )}

      <a
        href={finding.sourceUrl}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-block text-sm text-accent-foreground underline underline-offset-2"
      >
        View the original CDSCO document
      </a>
    </Card>
  );
}
