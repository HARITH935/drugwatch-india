import type { LatestAlerts } from "@/lib/backend";
import { batches, formatAlertMonth, formatCount } from "@/lib/format";

// Pure rendering, no fetching: the async server component in page.tsx fetches, this draws. That
// split is what makes it testable - React Testing Library can't render an async component.
export function LatestAlertsSummary({ data }: { data: LatestAlerts }) {
  if (!data.alertMonth) {
    return <p>No alert data has been loaded yet.</p>;
  }
  return (
    <section aria-labelledby="latest-heading" className="space-y-4">
      <h2 id="latest-heading" className="text-xl font-semibold">
        Latest alerts: {formatAlertMonth(data.alertMonth)}
      </h2>
      <p>
        {batches(data.findings)} reported as not of standard quality, by{" "}
        {formatCount(data.reportingLabs)} testing laboratories, naming {formatCount(data.companies)}{" "}
        manufacturers.
      </p>
      {/* The backend's own caveat: a busier month usually means more testing, not worse medicine. */}
      <p className="text-zinc-700 dark:text-zinc-300">{data.note}</p>
      {data.mostReportedMedicines.length > 0 && (
        <>
          <h3 className="font-semibold">Most reported this month</h3>
          <ol className="list-decimal space-y-1 pl-6">
            {data.mostReportedMedicines.map((medicine) => (
              <li key={medicine.productName}>
                {medicine.productName}: {batches(medicine.findings)} reported
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
