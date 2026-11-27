import { defineConfig, devices } from "@playwright/test";

// Ports of its own, so a run never collides with `npm run dev` on 3100 - or with another
// project's server on Next.js's default 3000, which is how this project came to avoid 3000.
const STUB_PORT = 18080;
const APP_PORT = 3101;

// Phase 12 step 5: the same suite can be pointed at the deployed site instead of a local build.
//   E2E_BASE_URL=https://... SITE_PASSWORD=... npx playwright test
// With a base URL supplied, the two local servers below are not started - production has its own -
// and the pre-launch password is sent on every request, since src/proxy.ts answers 401 without it.
const EXTERNAL_BASE_URL = process.env.E2E_BASE_URL;
const SITE_PASSWORD = process.env.SITE_PASSWORD;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI, // a stray test.only() must fail CI, not silently skip everything else
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: {
    baseURL: EXTERNAL_BASE_URL ?? `http://127.0.0.1:${APP_PORT}`,
    ...(SITE_PASSWORD
      ? {
          httpCredentials: {
            username: process.env.SITE_USERNAME ?? "drugwatch",
            password: SITE_PASSWORD,
          },
        }
      : {}),
  },
  // Most visitors will be on phones (plan Phase 11 step 5), so every test runs at both sizes.
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: EXTERNAL_BASE_URL
    ? undefined
    : [
        {
          command: "node e2e/stub-backend.mjs",
          url: `http://127.0.0.1:${STUB_PORT}/health`,
          env: { STUB_PORT: String(STUB_PORT) },
        },
        {
          // The production server, not `next dev`: what Partial Prerendering does at build time
          // is exactly what these tests need to cover. Run `npm run build` first.
          command: `npx next start --port ${APP_PORT}`,
          url: `http://127.0.0.1:${APP_PORT}`,
          env: { BACKEND_URL: `http://127.0.0.1:${STUB_PORT}` },
        },
      ],
});
