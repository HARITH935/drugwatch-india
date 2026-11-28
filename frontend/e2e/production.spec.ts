import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

/**
 * Checks that only make sense against the deployed site (Phase 12 step 5).
 *
 * **Why this file exists at all.** The rest of e2e/ runs against e2e/stub-backend.mjs and asserts
 * its fixtures by name - "Zyntophil", batch "TB-1201", "Marvex Labs". Those are invented, so they
 * can never appear in real CDSCO data: pointed at production, that suite fails 88 of 116 tests
 * while proving nothing about production. It is a contract test against a known backend, which is
 * the right thing for it to be, and the wrong tool for this job.
 *
 * So these tests assert only what must be true of the real thing, without naming any particular
 * finding: the lock keeps strangers out, pages render through the whole live chain (Vercel ->
 * Render API -> Neon), the published-data rules hold, and the accessibility work survives
 * deployment.
 *
 * Skipped unless E2E_BASE_URL is set, so a normal `npx playwright test` is unaffected:
 *   E2E_BASE_URL=https://... SITE_PASSWORD=... npx playwright test production.spec.ts
 *
 * **Warm the Render services first.** They spin down after 15 minutes idle and take 60-160s to
 * wake, which no assertion here waits for - a cold service fails these tests for a reason that
 * has nothing to do with the code.
 */

const BASE_URL = process.env.E2E_BASE_URL;

test.describe("the deployed site", () => {
  test.skip(!BASE_URL, "set E2E_BASE_URL to run these against a deployment");

  test("refuses a stranger with no password, and says how to authenticate", async () => {
    // Node's own fetch, not Playwright's request API. Playwright answers a Basic challenge by
    // retrying with the httpCredentials from playwright.config.ts, so every route through it -
    // the injected `request` fixture, an empty Authorization header, even a context built by
    // request.newContext() - reported 200 and hid the very thing this test exists to check.
    // fetch does nothing on a 401 except hand it back.
    const response = await fetch(`${BASE_URL}/`, { redirect: "manual" });

    expect(response.status).toBe(401);
    expect(response.headers.get("www-authenticate")).toContain("Basic");
    // A cached 401 would outlive the lock being lifted, and a cached page would outlive it being
    // put back.
    expect(response.headers.get("cache-control")).toContain("no-store");
  });

  test("locks sub-pages too, not just the home page", async () => {
    // A lock with holes in it is not a lock. /dashboards is the one that would matter most: it
    // embeds Superset, so a page served without the gate would also expose the dashboards.
    for (const path of ["/about", "/dashboards", "/drugs/search?q=telmisartan"]) {
      const response = await fetch(`${BASE_URL}${path}`, { redirect: "manual" });
      expect(response.status, `${path} should be locked`).toBe(401);
    }
  });

  test("renders the home page through the live backend", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { level: 1, name: "DrugWatch India" })).toBeVisible();
    // Not a fixture month: whatever the real archive's latest alert month happens to be. Seeing
    // any month at all proves the page reached the API, which reached gold on Neon.
    await expect(page.getByRole("heading", { name: /^Latest alerts: \w+ \d{4}$/ })).toBeVisible();
  });

  test("carries the disclaimer, as every page must (CLAUDE.md §6)", async ({ page }) => {
    await page.goto("/");

    await expect(
      page.getByText("Not medical advice. Data from CDSCO public alerts."),
    ).toBeVisible();
  });

  test("searches real CDSCO data and reaches a real drug page", async ({ page }) => {
    // A salt that is genuinely in the archive, rather than a fixture - but the assertions below
    // name no particular product, so they survive the data being refreshed each month.
    await page.goto("/drugs/search?q=telmisartan");

    const firstResult = page.getByRole("link").filter({ hasText: /telmisartan/i }).first();
    await expect(firstResult).toBeVisible();
    await firstResult.click();

    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(
      page.getByText("Not medical advice. Data from CDSCO public alerts."),
    ).toBeVisible();
  });

  test("tells an honest story for a batch that is not in the archive", async ({ page }) => {
    // CLAUDE.md §6: "not found" must never read as "guaranteed safe".
    await page.goto("/batches/search?drug=telmisartan&batch=NOT-A-REAL-BATCH-9999");

    await expect(page.getByText(/not found|no match|not in/i).first()).toBeVisible();
    await expect(page.getByText(/does not mean|not a guarantee|guaranteed safe/i).first()).toBeVisible();
  });

  test("the home page has no WCAG 2.1 A/AA violations in production", async ({ page }) => {
    // The accessibility work of Phase 11 step 7, re-checked against the deployed build rather
    // than trusted to have survived bundling and deployment.
    await page.goto("/");

    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
      .analyze();

    expect(results.violations).toEqual([]);
  });

  test("does not scroll sideways at phone width", async ({ page }) => {
    await page.setViewportSize({ width: 360, height: 800 });
    await page.goto("/");

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1); // 1px of rounding is not a scrollbar
  });
});
