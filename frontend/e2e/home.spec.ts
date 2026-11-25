import { expect, test } from "@playwright/test";

test("the home page shows the latest alert summary from the backend", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "DrugWatch India" })).toBeVisible();
  // These values exist only in e2e/fixtures/latest-alerts.json, so seeing them proves the page
  // really went Next.js server -> backend -> page, rather than rendering something built in.
  await expect(page.getByRole("heading", { name: "Latest alerts: September 2026" })).toBeVisible();
  await expect(page.getByText("12 batches reported as not of standard quality")).toBeVisible();
  await expect(page.getByText("Zyntophil Tablets 500 mg: 4 batches reported")).toBeVisible();
});

test("every page carries the disclaimer (CLAUDE.md §6)", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("Not medical advice. Data from CDSCO public alerts.")).toBeVisible();
});

test("nothing is wider than the screen", async ({ page }) => {
  // A sideways scroll on a phone is the most common way a "responsive" page quietly isn't.
  await page.goto("/");
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBe(0);
});
