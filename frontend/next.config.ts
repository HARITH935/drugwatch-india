import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";

import type { NextConfig } from "next";

// One .env for the whole repo (CLAUDE.md §10), but only the keys the frontend needs are read from
// it. The same file holds the database, JWT and Superset secrets, and this server has no business
// holding them - the least-privilege rule ml-serving's compose test already enforces for risk-api.
// A key already set in the real environment (CI, Phase 12's VM) wins over the file.
const FRONTEND_KEYS = ["BACKEND_URL"] as const;
const rootEnv = path.resolve(process.cwd(), "..", ".env");
if (existsSync(rootEnv)) {
  const parsed = parseEnv(readFileSync(rootEnv, "utf8"));
  for (const key of FRONTEND_KEYS) {
    if (parsed[key] !== undefined && process.env[key] === undefined) {
      process.env[key] = parsed[key];
    }
  }
}

const nextConfig: NextConfig = {
  // Next.js 16's data model: every server-side fetch is either cached or explicitly dynamic.
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false, // don't advertise the framework and version in every response
  // This app is the project root, stated rather than guessed: Next.js otherwise walks upwards
  // looking for lockfiles, and found an unrelated one in the home folder on this Mac.
  outputFileTracingRoot: process.cwd(),
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
