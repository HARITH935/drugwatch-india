import Link from "next/link";

import type { ManufacturerPage } from "@/lib/backend";
import { formatAlertMonth, formatCount } from "@/lib/format";

export function ManufacturerPageView({ page }: { page: ManufacturerPage }) {
  const { manufacturer } = page;
  const sameMonth = manufacturer.firstAlertMonth === manufacturer.lastAlertMonth;

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-2xl font-bold">{manufacturer.name}</h1>
        {manufacturer.state && <p className="text-muted-foreground">{manufacturer.state}</p>}

        <p>
          {formatCount(manufacturer.reportedBatches)} reported{" "}
          {manufacturer.reportedBatches === 1 ? "batch" : "batches"} across{" "}
          {formatCount(manufacturer.distinctMedicines)}{" "}
          {manufacturer.distinctMedicines === 1 ? "medicine" : "medicines"}
          {sameMonth
            ? ` in ${formatAlertMonth(manufacturer.firstAlertMonth)}`
            : ` between ${formatAlertMonth(manufacturer.firstAlertMonth)} and ${formatAlertMonth(manufacturer.lastAlertMonth)}`}
          .
        </p>
        {/* The backend's own wording (CLAUDE.md §6): a count of reported batches, never of
            "failures" - rendered verbatim so the page can't phrase it more strongly than the API. */}
        <p>{page.meaning}</p>
      </header>

      {/* The risk score is NOT here: it is its own, separately-fetched Suspense boundary in the
          page itself, because it is slower and can fail independently of this DB-only data -
          the same "everything else on this page is unaffected" promise the backend's own
          RiskResult.unavailable() makes. */}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold">Medicines</h2>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border text-muted-foreground">
              <th className="py-2 font-medium">Medicine</th>
              <th className="py-2 text-right font-medium">Batches reported</th>
              <th className="py-2 text-right font-medium">Last alert</th>
            </tr>
          </thead>
          <tbody>
            {page.medicines.map((medicine) => (
              <tr key={medicine.drugId} className="border-b border-border last:border-0">
                <td className="py-2">
                  <Link
                    href={`/drugs/${medicine.drugId}`}
                    className="text-accent-foreground underline underline-offset-2"
                  >
                    {medicine.productName}
                  </Link>
                </td>
                <td className="py-2 text-right">{formatCount(medicine.reportedBatches)}</td>
                <td className="py-2 text-right">{formatAlertMonth(medicine.lastAlertMonth)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
