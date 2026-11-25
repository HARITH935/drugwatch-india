# ADR 0020 — Frontend tooling, and how the site gets its data

- **Status:** Accepted
- **Date:** 2026-11-24
- **Decided by:** Harith (project owner) — Phase 11 decisions B, C and D ("take all recommendations")
- **Affects:** `frontend/` (Phase 11), CI's new `frontend` job, and Phase 12's deployment

---

## Context

The plan's §6 fixes the frontend at **Next.js, Tailwind CSS and the Superset embedded SDK**, and
§14 asks for "component tests for key pages, basic end-to-end flow (search → result)" without
naming tools. ADR 0005 settled the same questions for Python (uv, pytest, ruff) and ADR 0018 for
Java (Maven, Spotless, ArchUnit). This records the answers for the website, plus two design
decisions every later Phase 11 step depends on.

## Decision

### 1. Tooling

| Need | Choice | Why |
|---|---|---|
| Package manager | **npm** + `package-lock.json`, `npm ci` in CI | Already installed with Node; `npm ci` installs exactly the lockfile, like `uv sync --locked` |
| Format | **Prettier**, `printWidth: 100` | The same line length as ruff and Spotless across the repo |
| Lint | **ESLint** with `eslint-config-next` | Ships with Next.js; includes React's hooks rules |
| Component tests | **Vitest + React Testing Library + jsdom** | pytest's role for components; no extra JSX plugin needed |
| End-to-end tests | **Playwright**, Chromium only, desktop *and* phone sizes | §14's search → result flow; most visitors are on phones |
| Runtime | **Node 22** (`engines: >=22`, `engine-strict`) | The major this Mac runs |

**Versions.** Next.js, React, Tailwind, ESLint and TypeScript are the set `create-next-app@16.4.6`
generates, because those are tested together by the people who ship them. Every tool added on top
is pinned exactly at the newest release **at least 14 days old** - most compromised npm releases
are caught and pulled within days. `.npmrc` keeps `save-exact` and `engine-strict` on, and
`engine-strict` earned its place on day one: it refused `jsdom` 31, which needs Node 22.22, at
install time instead of letting it fail strangely later (`jsdom` 29.1.1 is used instead).

**npm's own bug.** The npm that ships with Node 22 (10.9.2) crashes resolving Vitest's optional
peer dependencies (`Cannot read properties of null (reading 'edgesOut')`, inside npm's resolver).
npm 11 does not. So **changing** the lockfile uses `npx npm@11.21.2 install`, but **installing**
from it (`npm ci`) skips the resolver and works with the stock npm - proven on this Mac by deleting
`node_modules` and running `npm ci` with 10.9.2. CI needs no npm upgrade.

**A stub backend for end-to-end tests.** CI has no Spring, Postgres or Redis, so Playwright runs
the production build against `e2e/stub-backend.mjs`, which serves invented fixtures (ADR 0003: no
real CDSCO rows in git). A stub's failure mode is drifting from the real API while every test
stays green, so two guards exist: `tsc` checks each fixture against its TypeScript type, and
`src/lib/backend.contract.test.ts` compares the fixture's fields with the **live** backend whenever
one is reachable (skipped otherwise, like the backend's own `GoldContractTest`).

### 2. The browser's only backend is the Next.js server (decision B)

The browser never calls Spring. Pages are server components that fetch from `BACKEND_URL` on the
server; that variable has no `NEXT_PUBLIC_` prefix, so Next.js never puts it in browser JavaScript
(verified: the served HTML contains no `localhost:8080`). Step 4 extends this to login: the
Next.js server will hold the JWTs in **httpOnly, Secure, SameSite cookies**, which the browser
stores but page scripts cannot read. Consequences: Spring needs no CORS configuration at all, and a
script injected into the page has no token to steal.

`next.config.ts` reads the repo-root `.env` (one config file, as every other project does), but
**only the keys the frontend needs** - today just `BACKEND_URL`. That file also holds the database,
JWT and Superset secrets, and this server has no business holding them: the same least-privilege
rule `ml-serving`'s compose test enforces for the risk service.

### 3. One cache, and it isn't Next.js's

Next.js 16's Cache Components (`cacheComponents: true`) make every server-side fetch either cached
(`'use cache'`) or explicitly dynamic. **Backend data is fetched dynamically, per request, and
never cached in Next.js.** Two reasons:

- Spring already caches these lookups in Redis **keyed by the data's alert month** (Phase 9 step 6),
  so a monthly load invalidates them by itself. A second, *time-based* cache here could keep
  serving last month's alerts after a new month lands - the exact failure Phase 9's `CacheConfig`
  was designed to make impossible.
- A `'use cache'` component is prerendered at **build** time, so `next build` would need a running
  backend. CI has none. The build is verified to succeed with `BACKEND_URL` pointing at a dead
  port, and Next.js reports the home page as *Partial Prerender*: the static shell is prebuilt,
  the data streams in per request.

### 4. No UI component or chart library (decision D)

Tailwind plus a small set of hand-built components; small charts as plain SVG, heavier ones left
to Superset (already approved). Nothing extra to approve, and less JavaScript on a phone.

## Consequences

- **Port 3100, not Next.js's default 3000** - another project on this Mac already runs a Next.js
  server on 3000. The backend's `SITE_URL` (the base of links in verification and watchlist emails)
  moves to `http://localhost:3100` with it; e2e uses 3101 and the stub 18080, so a test run never
  collides with `npm run dev`.
- A backend that is down or slow (5 s timeout) shows a calm "unavailable right now" message with
  the disclaimer still on the page - HTTP 200, not an error page. Verified with a dead `BACKEND_URL`.
- Phase 12 inherits a server that needs `BACKEND_URL` set, and a site whose security relies on the
  browser never seeing a token - so the Phase 12 reverse proxy must forward cookies, and must not
  expose Spring's port publicly.
