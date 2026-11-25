import { defineConfig, devices } from "@playwright/test";

// Ports of its own, so a run never collides with `npm run dev` on 3100 - or with another
// project's server on Next.js's default 3000, which is how this project came to avoid 3000.
const STUB_PORT = 18080;
const APP_PORT = 3101;

export default defineConfig({
  testDir: "./e2e",
  forbidOnly: !!process.env.CI, // a stray test.only() must fail CI, not silently skip everything else
  retries: process.env.CI ? 1 : 0,
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${APP_PORT}` },
  // Most visitors will be on phones (plan Phase 11 step 5), so every test runs at both sizes.
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: "node e2e/stub-backend.mjs",
      url: `http://127.0.0.1:${STUB_PORT}/health`,
      env: { STUB_PORT: String(STUB_PORT) },
    },
    {
      // The production server, not `next dev`: what Partial Prerendering does at build time is
      // exactly what these tests need to cover. Run `npm run build` first.
      command: `npx next start --port ${APP_PORT}`,
      url: `http://127.0.0.1:${APP_PORT}`,
      env: { BACKEND_URL: `http://127.0.0.1:${STUB_PORT}` },
    },
  ],
});
