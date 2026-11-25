// A stand-in for the Spring API, for Playwright runs without the real backend (CI has no Postgres).
// Serves invented fixtures (ADR 0003: no real CDSCO rows in git) in the shape Spring really sends.
// Two guards keep it honest: tsc checks each fixture against its TypeScript type, and
// src/lib/backend.contract.test.ts compares the fixtures' fields with the LIVE backend when one runs.
import { readFileSync } from "node:fs";
import { createServer } from "node:http";

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));

const ROUTES = {
  "/api/v1/alerts/latest": fixture("latest-alerts.json"),
};

const port = Number(process.env.STUB_PORT ?? 18080);

createServer((request, response) => {
  const path = new URL(request.url ?? "/", "http://stub").pathname;
  if (path === "/health") {
    response.writeHead(200).end("ok"); // Playwright waits on this before starting the tests
    return;
  }
  const body = ROUTES[path];
  // An unstubbed path is a 404, never an empty 200: a test must not pass against data it never set up.
  response.writeHead(body ? 200 : 404, { "content-type": "application/json" });
  response.end(JSON.stringify(body ?? { error: `not stubbed: ${path}` }));
}).listen(port, "127.0.0.1", () => console.log(`stub backend on http://127.0.0.1:${port}`));
