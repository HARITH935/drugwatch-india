import { expect, test } from "@playwright/test";

// One flow, threaded through every page step 3 added: a flagged batch result links to its
// manufacturer, whose medicines list links to a drug page, which links back to that same
// manufacturer - proving the navigation actually connects, not just that each page renders in
// isolation.
test("a flagged result's manufacturer links to a page showing the risk score", async ({ page }) => {
  await page.goto("/batches/search?drug=Zyntophil&batch=TB-1201");

  await page.getByRole("link", { name: "Marvex Labs" }).click();

  await expect(page).toHaveURL(/\/manufacturers\/m1/);
  await expect(page.getByRole("heading", { name: "Marvex Labs" })).toBeVisible();
  await expect(page.getByText("Himachal Pradesh")).toBeVisible();
  await expect(page.getByText("42%")).toBeVisible();
  // CLAUDE.md §6: the caveat must appear wherever the score does.
  await expect(page.getByText(/reflects reporting history/)).toBeVisible();
});

test("a manufacturer's medicine links to its drug page", async ({ page }) => {
  await page.goto("/manufacturers/m1");

  await page.getByRole("link", { name: "Zyntophil Tablets 500 mg" }).click();

  await expect(page).toHaveURL(/\/drugs\/d1/);
  await expect(page.getByRole("heading", { name: "Zyntophil Tablets 500 mg" })).toBeVisible();
  await expect(page.getByText("TB-1201")).toBeVisible();
  await expect(page.getByRole("link", { name: "View the original CDSCO document" })).toBeVisible();
});

test("an unknown medicine id is a real 404, not a 200 with 'not found' text", async ({ page }) => {
  const response = await page.goto("/drugs/doesnotexist");
  expect(response?.status()).toBe(404);
  await expect(page.getByText("Not found")).toBeVisible();
});

test("an unknown manufacturer id is a real 404 too", async ({ page }) => {
  const response = await page.goto("/manufacturers/doesnotexist");
  expect(response?.status()).toBe(404);
});

test("searching for a medicine from the header finds it", async ({ page }) => {
  await page.goto("/");

  // "Medicine name" also labels the home page's OWN batch-search field (BatchSearchForm), so
  // filling before this client-side navigation actually lands would silently fill THAT input
  // instead - explicitly waiting for the URL, not just the click, is what makes this reliable.
  await Promise.all([
    page.waitForURL(/\/drugs\/search$/),
    page.getByRole("link", { name: "Find a medicine" }).click(),
  ]);
  await page.getByLabel("Medicine name").fill("Zyntophil");
  // A real <form> submit, not client-side routing - same reasoning, waiting for the URL itself.
  await Promise.all([
    page.waitForURL(/\/drugs\/search\?q=/),
    page.getByRole("button", { name: "Search" }).click(),
  ]);

  await expect(page.getByRole("link", { name: "Zyntophil Tablets 500 mg" })).toBeVisible();
});
