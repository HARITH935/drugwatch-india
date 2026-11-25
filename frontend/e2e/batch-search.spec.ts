import { expect, test } from "@playwright/test";

// The plan's own required flow (§14: "basic end-to-end flow (search → result)"), driven through
// the real <form> on the home page - no JavaScript shortcuts, the same path a visitor takes.
test("searching from the home page reaches a flagged result", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("Medicine name").fill("Zyntophil");
  await page.getByLabel("Batch number").fill("TB-1201");
  await page.getByRole("button", { name: "Check this batch" }).click();

  await expect(page).toHaveURL(/\/batches\/search\?drug=Zyntophil&batch=TB-1201/);
  await expect(page.getByRole("heading", { name: "Zyntophil — batch TB-1201" })).toBeVisible();
  await expect(page.getByText("Reported in a CDSCO alert")).toBeVisible();
  await expect(page.getByText("Marvex Labs")).toBeVisible();
  await expect(page.getByRole("link", { name: "View the original CDSCO document" })).toBeVisible();
});

test("a batch that isn't in the archive says so, without implying it's safe", async ({ page }) => {
  await page.goto("/");

  await page.getByLabel("Medicine name").fill("Zyntophil");
  await page.getByLabel("Batch number").fill("ZZ-0000");
  await page.getByRole("button", { name: "Check this batch" }).click();

  await expect(page.getByText("No matching alert found")).toBeVisible();
  await expect(page.getByText(/not a guarantee of safety/)).toBeVisible();
});

test("a medicine name that's too short is rejected with a plain explanation", async ({ page }) => {
  await page.goto("/batches/search?drug=ab&batch=TB-1201");

  await expect(page.getByText(/medicine name/)).toBeVisible();
  await expect(page.getByRole("link", { name: "Try again" })).toBeVisible();
});

test("visiting the result page with nothing typed prompts for a search, not an error", async ({
  page,
}) => {
  await page.goto("/batches/search");

  await expect(page.getByText(/Enter a medicine name and a batch number/)).toBeVisible();
});
