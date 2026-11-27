import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { parseEnv } from "node:util";

import type { NextConfig } from "next";

// One .env for the whole repo (CLAUDE.md §10), but only the keys the frontend needs are read from
// it. The same file holds the database, JWT and Superset secrets, and this server has no business
// holding them - the least-privilege rule ml-serving's compose test already enforces for risk-api.
// A key already set in the real environment (CI, Phase 12's VM) wins over the file.
// SITE_USERNAME/SITE_PASSWORD drive the pre-launch lock in src/proxy.ts. They are read at BUILD
// time, not request time: the proxy runs on the edge runtime, where Next inlines the `process.env`
// keys a module references. So changing or removing the password needs a redeploy, which is the
// honest shape for "launch = unset it" anyway - it is a deliberate act, not a toggle someone can
// flip by accident.
const FRONTEND_KEYS = [
  "BACKEND_URL",
  "NEXT_PUBLIC_SUPERSET_URL",
  "SITE_USERNAME",
  "SITE_PASSWORD",
] as const;
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
  // Cache Components (Partial Prerendering) was tried and reverted - ADR 0020's amendment
  // explains why: on this version, a dynamic-segment page's notFound() answers HTTP 200 once
  // the page has started streaming, which an unknown drug/manufacturer id hits on every route
  // that has one. Classic dynamic rendering gives a correct 404 and costs this project almost
  // nothing, since nearly every page here needs live backend data anyway - there is no
  // meaningful static shell to prerender in the first place.
  cacheComponents: false,
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
