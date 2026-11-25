// Wording helpers. CLAUDE.md §6 asks for neutral counts ("number of NSQ batches reported"), so
// every count on the site goes through these rather than being phrased page by page.

const MONTH = /^(\d{4})-(0[1-9]|1[0-2])$/;

/** "2026-09" -> "September 2026". Anything that isn't a month is returned unchanged. */
export function formatAlertMonth(month: string): string {
  const match = MONTH.exec(month);
  if (!match) return month;
  const date = new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, 1));
  // UTC on both sides, so a server in another time zone can't shift it into the previous month.
  return new Intl.DateTimeFormat("en-IN", {
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  }).format(date);
}

/** An ISO instant (Java's `Instant.toString()`) -> "25 November 2026", in IST - fixed rather
 * than the server's own time zone, so the date doesn't depend on where this happens to run. */
export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Asia/Kolkata",
  }).format(new Date(iso));
}

/** Indian digit grouping: 7126 -> "7,126", 150000 -> "1,50,000". */
export function formatCount(n: number): string {
  return n.toLocaleString("en-IN");
}

/** "1 batch" / "330 batches". */
export function batches(n: number): string {
  return `${formatCount(n)} ${n === 1 ? "batch" : "batches"}`;
}

// ApiProblem.detail's keys are the backend's own request-parameter names ("drug", "batch"),
// which are fine in a log but not what a visitor typed into the form - this is the one place
// that gap is bridged, so a validation message reads as the site's, not the API's.
const FIELD_LABELS: Record<string, string> = {
  drug: "medicine name",
  batch: "batch number",
};

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field] ?? field;
}
