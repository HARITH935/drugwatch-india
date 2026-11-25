// A stand-in for the Spring API, for Playwright runs without the real backend (CI has no Postgres).
// Serves invented fixtures (ADR 0003: no real CDSCO rows in git) in the shape Spring really sends.
// Two guards keep it honest: tsc checks each fixture against its TypeScript type, and
// src/lib/backend.contract.test.ts compares the fixtures' fields with the LIVE backend when one runs.
import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));

const ROUTES = {
  "/api/v1/alerts/latest": () => [200, fixture("latest-alerts.json")],
  "/api/v1/batches/search": (query) => batchSearch(query),
  "/api/v1/drugs/d1": () => [200, fixture("drug-page.json")],
  "/api/v1/drugs/search": (query) => drugSearch(query),
  "/api/v1/manufacturers/m1": () => [200, fixture("manufacturer-page.json")],
  "/api/v1/manufacturers/m1/risk": () => [200, fixture("risk-score.json")],
  "/api/v1/auth/register": () => [202, { status: "accepted" }],
  "/api/v1/auth/login": (_query, body) => login(body),
  "/api/v1/auth/refresh": (_query, body) => refresh(body),
  "/api/v1/auth/logout": () => [204, null],
  "/api/v1/auth/verify": (_query, body) => verify(body),
};

function problem(status, message) {
  return [
    status,
    {
      status,
      error: message,
      detail: {},
      at: new Date().toISOString(),
      disclaimer: "Not medical advice. Data from CDSCO public alerts.",
    },
  ];
}

function notFoundProblem(message) {
  return problem(404, message);
}

// A fixed account, not a real database - enough to exercise login/logout/refresh's happy and
// unhappy paths. The access token is shaped like AccessTokens.issue()'s real JWT (header.payload.
// signature, exp in the payload) so session.ts's expiry check has something real to decode; the
// "signature" is never checked by anything in this project (see jwt.ts's own comment).
const TEST_ACCOUNT = { email: "sentinel@example.com", password: "a-secret-password-12" };
let currentRefreshToken = "stub-refresh-token-1";

function mintAccessToken(email, lifetimeSeconds) {
  const part = (value) => Buffer.from(JSON.stringify(value)).toString("base64url");
  const exp = Math.floor(Date.now() / 1000) + lifetimeSeconds;
  return `${part({ alg: "none" })}.${part({ sub: email, exp })}.stub-signature`;
}

function tokens(email) {
  const expiresInSeconds = 900; // AccessTokens.LIFETIME
  currentRefreshToken = `stub-refresh-token-${Math.random().toString(36).slice(2)}`;
  return {
    accessToken: mintAccessToken(email, expiresInSeconds),
    refreshToken: currentRefreshToken,
    expiresInSeconds,
    emailVerified: true,
  };
}

function login(body) {
  const email = (body?.email ?? "").trim().toLowerCase();
  if (email !== TEST_ACCOUNT.email || body?.password !== TEST_ACCOUNT.password) {
    // The exact wording AuthController returns for both cases - see login/page.tsx's own comment.
    return problem(401, "Email or password is not correct");
  }
  return [200, tokens(email)];
}

function refresh(body) {
  if (!body?.refreshToken || body.refreshToken !== currentRefreshToken) {
    return problem(401, "That session has ended. Please log in again.");
  }
  return [200, tokens(TEST_ACCOUNT.email)];
}

function verify(body) {
  if (body?.token !== "valid-token") {
    return problem(401, "That verification link is not valid");
  }
  return [200, { status: "verified" }];
}

function drugSearch(query) {
  const q = query.get("q") ?? "";
  const matches = q.toLowerCase().includes("zyntophil") ? [fixture("drug-page.json").drug] : [];
  return [
    200,
    {
      query: q,
      matches,
      note: "Medicines are listed as CDSCO printed them, so the same medicine can appear more than once under different spellings.",
      disclaimer: "Not medical advice. Data from CDSCO public alerts.",
    },
  ];
}

// Mirrors BatchController's own validation (@Size(min=3)/@Size(min=1)) closely enough to exercise
// the frontend's 400 handling - not a reimplementation of Spring's, just enough to prove the
// page's error path works against a shape GlobalExceptionHandler really sends.
function batchSearch(query) {
  const drug = query.get("drug") ?? "";
  const batch = query.get("batch") ?? "";
  if (drug.length < 3) {
    return [
      400,
      {
        status: 400,
        error: "One or more parameters are not valid",
        detail: { drug: "size must be between 3 and 120" },
        at: new Date().toISOString(),
        disclaimer: "Not medical advice. Data from CDSCO public alerts.",
      },
    ];
  }
  if (drug.toLowerCase().includes("zyntophil") && batch === "TB-1201") {
    return [200, fixture("batch-flagged.json")];
  }
  return [200, { ...fixture("batch-not-found.json"), drug, batch }];
}

const port = Number(process.env.STUB_PORT ?? 18080);

function readJsonBody(request) {
  return new Promise((resolve) => {
    let raw = "";
    request.on("data", (chunk) => (raw += chunk));
    request.on("end", () => {
      try {
        resolve(raw ? JSON.parse(raw) : undefined);
      } catch {
        resolve(undefined);
      }
    });
  });
}

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://stub");
  if (url.pathname === "/health") {
    response.writeHead(200).end("ok"); // Playwright waits on this before starting the tests
    return;
  }
  let route = ROUTES[url.pathname];
  // An id this stub doesn't know about mirrors the real NotFoundException - the same message
  // DrugService/ManufacturerService actually throw - rather than an unhelpful blanket 404.
  if (!route && /^\/api\/v1\/drugs\/[^/]+$/.test(url.pathname)) {
    route = () => notFoundProblem("No such medicine");
  }
  if (!route && /^\/api\/v1\/manufacturers\/[^/]+$/.test(url.pathname)) {
    route = () => notFoundProblem("No such company");
  }
  // An unstubbed path is a 404, never an empty 200: a test must not pass against data it never set up.
  if (!route) {
    response.writeHead(404, { "content-type": "application/json" });
    response.end(JSON.stringify({ error: `not stubbed: ${url.pathname}` }));
    return;
  }
  const body = request.method === "POST" ? await readJsonBody(request) : undefined;
  const [status, responseBody] = await route(url.searchParams, body);
  response.writeHead(status, { "content-type": "application/json" });
  response.end(status === 204 ? undefined : JSON.stringify(responseBody));
}).listen(port, "127.0.0.1", () => console.log(`stub backend on http://127.0.0.1:${port}`));
