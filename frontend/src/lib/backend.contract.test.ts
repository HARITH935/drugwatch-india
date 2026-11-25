// @vitest-environment node
//
// The e2e stub serves fixtures in place of Spring. A stub's failure mode is drifting: the real
// API gains or renames a field, the stub doesn't, and every e2e test keeps passing against a shape
// that no longer exists. Two guards:
//   1. at type-check time, each fixture must satisfy its TypeScript type (below), and
//   2. when a real backend is reachable, its response must have exactly the fixture's fields.
// Without a backend (CI) the second is skipped, like the backend's own GoldContractTest.
import { describe, expect, it } from "vitest";

import batchFlaggedFixture from "../../e2e/fixtures/batch-flagged.json";
import latestAlertsFixture from "../../e2e/fixtures/latest-alerts.json";

import { backendUrl, type BatchSearchResult, type LatestAlerts } from "./backend";

// Guard 1: tsc fails here if a fixture and its type disagree. `outcome` is cast because JSON
// import types widen a literal union to `string` - the runtime check right after it is what
// still catches a fixture whose value isn't actually one of the three real outcomes.
const typedFixture: LatestAlerts = latestAlertsFixture;
const typedBatchFixture: BatchSearchResult = {
  ...batchFlaggedFixture,
  outcome: batchFlaggedFixture.outcome as BatchSearchResult["outcome"],
};
if (!["FLAGGED", "NOT_FOUND", "NOT_SEARCHABLE"].includes(typedBatchFixture.outcome)) {
  throw new Error(
    `batch-flagged.json has an outcome that doesn't exist: ${typedBatchFixture.outcome}`,
  );
}

async function backendIsUp(): Promise<boolean> {
  try {
    // 5 s, not 1.5 s: the first version skipped on a cold run, with four test workers starting
    // at once, while the backend was up - a contract test that silently skips is green while
    // checking nothing. With NO backend (CI) the connection is refused instantly, so a longer
    // timeout costs nothing there; it only matters when a backend exists but is slow.
    const response = await fetch(`${backendUrl()}/actuator/health`, {
      signal: AbortSignal.timeout(5_000),
    });
    return response.ok;
  } catch {
    return false;
  }
}

const live = await backendIsUp();

describe.skipIf(!live)("contract with the live backend", () => {
  it("GET /api/v1/alerts/latest has exactly the fields the stub fixture has", async () => {
    const real = await (await fetch(`${backendUrl()}/api/v1/alerts/latest`)).json();

    expect(Object.keys(real).sort()).toEqual(Object.keys(typedFixture).sort());
    expect(Object.keys(real.mostReportedMedicines[0]).sort()).toEqual(
      Object.keys(typedFixture.mostReportedMedicines[0]).sort(),
    );
  });

  it("GET /api/v1/batches/search has exactly the fixture's fields, outcome included", async () => {
    // A query guaranteed not to match anything real, rather than a hand-picked real drug name -
    // this only needs the SHAPE of a response, and a shape-only query can't go stale the way a
    // real drug/batch pair eventually could if that finding is reprocessed out of the archive.
    const query = new URLSearchParams({ drug: "zzznosuchmedicinezzz", batch: "zzz" });
    const real = await (await fetch(`${backendUrl()}/api/v1/batches/search?${query}`)).json();

    expect(Object.keys(real).sort()).toEqual(Object.keys(typedBatchFixture).sort());
    expect(real.outcome).toBe("NOT_FOUND"); // confirms the query really didn't match anything
  });

  // Login/verify success responses aren't checked here: a success would either need a real
  // account's credentials (not something to commit) or would create one in Harith's local
  // Postgres on every test run. The ApiProblem shape on the error path is free to check and
  // exercises the same GlobalExceptionHandler every other endpoint goes through.
  it("POST /api/v1/auth/login answers a bad password with GlobalExceptionHandler's shape", async () => {
    const response = await fetch(`${backendUrl()}/api/v1/auth/login`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: "no-such-account@example.com", password: "wrong-password" }),
    });
    const real = await response.json();

    expect(response.status).toBe(401);
    expect(Object.keys(real).sort()).toEqual(["at", "detail", "disclaimer", "error", "status"]);
  });

  it("POST /api/v1/auth/verify answers a bad token with GlobalExceptionHandler's shape", async () => {
    const response = await fetch(`${backendUrl()}/api/v1/auth/verify`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token: "zzznosuchtokenzzz" }),
    });
    const real = await response.json();

    expect(response.status).toBe(401);
    expect(Object.keys(real).sort()).toEqual(["at", "detail", "disclaimer", "error", "status"]);
  });
});
