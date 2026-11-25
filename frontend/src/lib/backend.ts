// The Spring Boot API, called from this Next.js server only (Phase 11 decision B: the browser's
// one backend is this server, never Spring directly). BACKEND_URL has no NEXT_PUBLIC_ prefix, so
// Next.js never puts it in browser JavaScript; this module is imported by server components only.

const DEFAULT_BACKEND_URL = "http://localhost:8080";
const TIMEOUT_MS = 5_000; // a hung backend must not hang the page: it shows a calm fallback instead

export function backendUrl(): string {
  return process.env.BACKEND_URL ?? DEFAULT_BACKEND_URL;
}

/** GlobalExceptionHandler.problem()'s error body shape - present whenever a response isn't ok. */
export type ApiProblem = {
  status: number;
  error: string;
  detail: Record<string, string>; // e.g. {"drug": "size must be between 3 and 120"}
  at: string;
  disclaimer: string;
};

/** The backend could not be reached, or answered with an error status. */
export class BackendError extends Error {
  constructor(
    readonly status: number | null,
    message: string,
    /** The parsed error body, when the backend was reachable and answered with one. */
    readonly problem: ApiProblem | null = null,
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
    // Best-effort: GlobalExceptionHandler always sends JSON, but a proxy or a timeout page in
    // front of it might not - a response body that isn't JSON must not crash the error path too.
    const problem = await response.json().catch(() => null);
    throw new BackendError(
      response.status,
      `backend answered ${response.status} for ${path}`,
      problem,
    );
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

/** Finding.java. `manufacturerName` is null exactly when `spurious` is true (enforced server-side) -
 * render `nameOnPack`, never a manufacturer, for a spurious row. */
export type Finding = {
  batchNumber: string;
  alertMonth: string;
  productName: string;
  failureReason: string | null;
  failureCategories: string[];
  spurious: boolean;
  nameOnPack: string | null;
  manufacturerId: string | null;
  manufacturerName: string | null;
  reportedBy: string | null;
  labType: string | null;
  sourceUrl: string; // always present (CLAUDE.md §6): the Finding constructor itself guarantees it
};

/** BatchSearchResult.java (GET /api/v1/batches/search) */
export type BatchSearchResult = {
  drug: string;
  batch: string;
  outcome: "FLAGGED" | "NOT_FOUND" | "NOT_SEARCHABLE";
  findings: Finding[];
  sameBatchOtherMedicines: Finding[];
  meaning: string; // the backend's own wording for this outcome - rendered verbatim, never reworded
  disclaimer: string;
};

export function searchBatch(drug: string, batch: string): Promise<BatchSearchResult> {
  const query = new URLSearchParams({ drug, batch });
  return backendGet<BatchSearchResult>(`/api/v1/batches/search?${query}`);
}

/** DrugSummary.java */
export type DrugSummary = {
  drugId: string;
  productName: string;
  genericName: string | null;
  dosageForm: string | null;
  strengths: string[];
  drugClasses: string[];
  findings: number;
  firstAlertMonth: string;
  lastAlertMonth: string;
};

/** DrugService.DrugPage (GET /api/v1/drugs/{id}) */
export type DrugPage = {
  drug: DrugSummary;
  findings: Finding[];
  meaning: string;
  disclaimer: string;
};

/** DrugService.DrugSearchResult (GET /api/v1/drugs/search) */
export type DrugSearchResult = {
  query: string;
  matches: DrugSummary[];
  note: string; // same-medicine-different-spelling caveat - rendered verbatim, never reworded
  disclaimer: string;
};

export function getDrug(id: string): Promise<DrugPage> {
  return backendGet<DrugPage>(`/api/v1/drugs/${encodeURIComponent(id)}`);
}

export function searchDrugs(q: string, limit = 20): Promise<DrugSearchResult> {
  const query = new URLSearchParams({ q, limit: String(limit) });
  return backendGet<DrugSearchResult>(`/api/v1/drugs/search?${query}`);
}

/** ManufacturerService.Manufacturer */
export type Manufacturer = {
  manufacturerId: string;
  name: string;
  state: string | null;
  firstAlertMonth: string;
  lastAlertMonth: string;
  reportedBatches: number;
  alertMonths: number;
  distinctMedicines: number;
};

/** ManufacturerService.ReportedMedicine - a different shape from AlertService's, despite the name. */
export type ManufacturerMedicine = {
  drugId: string;
  productName: string;
  reportedBatches: number;
  lastAlertMonth: string;
};

/** ManufacturerService.ManufacturerPage (GET /api/v1/manufacturers/{id}) */
export type ManufacturerPage = {
  manufacturer: Manufacturer;
  medicines: ManufacturerMedicine[];
  meaning: string;
  disclaimer: string;
};

export function getManufacturer(id: string): Promise<ManufacturerPage> {
  return backendGet<ManufacturerPage>(`/api/v1/manufacturers/${encodeURIComponent(id)}`);
}

/** RiskService.RiskResult (GET /api/v1/manufacturers/{id}/risk).
 *
 * `available` is false for TWO distinct reasons the backend tells apart only in `meaning`'s
 * wording, never in a separate field: no reporting history at all ("not scoreable"), or the
 * scoring service being down right now ("unavailable"). The frontend doesn't need to tell them
 * apart either - both cases render the same way, `meaning` alone, with no numeric score. */
export type RiskResult = {
  manufacturerId: string;
  name: string;
  available: boolean;
  score: number | null;
  featuresAsOfMonth: string | null;
  modelHasSeenThisCompany: boolean | null;
  explanation: string[]; // plain-English SHAP sentences, already in CLAUDE.md §6's approved wording
  accuracyNote: string | null;
  meaning: string; // CLAUDE.md §6: "say so wherever it is shown" - rendered with the score, always
  disclaimer: string;
};

export function getRiskScore(manufacturerId: string): Promise<RiskResult> {
  return backendGet<RiskResult>(`/api/v1/manufacturers/${encodeURIComponent(manufacturerId)}/risk`);
}
