import type { DrugPage } from "@/lib/backend";
import { formatAlertMonth } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

import { FindingCard } from "./FindingCard";

export function DrugPageView({ page }: { page: DrugPage }) {
  const { drug } = page;
  const sameMonth = drug.firstAlertMonth === drug.lastAlertMonth;

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">{drug.productName}</h1>
        {drug.genericName && <p className="text-muted-foreground">{drug.genericName}</p>}

        <div className="flex flex-wrap gap-1.5">
          {drug.dosageForm && <Badge variant="neutral">{drug.dosageForm}</Badge>}
          {drug.strengths.map((strength) => (
            <Badge key={strength} variant="neutral">
              {strength}
            </Badge>
          ))}
          {drug.drugClasses.map((drugClass) => (
            <Badge key={drugClass} variant="neutral">
              {drugClass}
            </Badge>
          ))}
        </div>

        <p>
          {drug.findings} {drug.findings === 1 ? "batch" : "batches"} reported
          {sameMonth
            ? ` in ${formatAlertMonth(drug.firstAlertMonth)}`
            : ` between ${formatAlertMonth(drug.firstAlertMonth)} and ${formatAlertMonth(drug.lastAlertMonth)}`}
          .
        </p>
        <p>{page.meaning}</p>
      </header>

      <section className="space-y-4">
        {page.findings.map((finding, index) => (
          <FindingCard
            key={`${finding.batchNumber}-${finding.alertMonth}-${index}`}
            finding={finding}
          />
        ))}
      </section>
    </div>
  );
}
