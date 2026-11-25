// The Spring Boot API, called from this Next.js server only (Phase 11 decision B: the browser's
// one backend is this server, never Spring directly). BACKEND_URL has no NEXT_PUBLIC_ prefix, so
// Next.js never puts it in browser JavaScript; this module is imported by server components only.

const DEFAULT_BACKEND_URL = "http://localhost:8080";
const TIMEOUT_MS = 5_000; // a hung backend must not hang the page: it shows a calm fallback instead

export function backendUrl(): string {
  return process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL;
}

/** The backend could not be reached, or answered with an error status. */
export class BackendError extends Error {
  constructor(
    readonly status: number | null,
    message: string,
  ) {
    super(message);
    this.name = "BackendError";
  }
}

export async function backendGet<T>(path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${backendUrl()}${path}`, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (error) {
    throw new BackendError(null, `backend unreachable for ${path}: ${String(error)}`);
  }
  if (!response.ok) {
    throw new BackendError(response.status, `backend answered ${response.status} for ${path}`);
  }
  return (await response.json()) as T;
}

// --- response shapes, mirroring the Spring records they come from -----------------------------

/** AlertService.ReportedMedicine */
export type ReportedMedicine = {
  productName: string;
  findings: number;
};

/** AlertService.LatestAlerts (GET /api/v1/alerts/latest) */
export type LatestAlerts = {
  alertMonth: string | null; // "2026-09"; null before any data is loaded
  findings: number;
  reportingLabs: number;
  companies: number;
  mostReportedMedicines: ReportedMedicine[];
  note: string; // the backend's own caveat: more findings usually means more testing
  disclaimer: string;
};
