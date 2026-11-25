import { expect, test } from "@playwright/test";

const EMAIL = "sentinel@example.com";
const PASSWORD = "a-secret-password-12";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL("/");
}

test("visiting the watchlist while logged out prompts for a login, not an error", async ({
  page,
}) => {
  await page.goto("/watchlist");

  await expect(page.getByRole("heading", { name: "Your watchlist" })).toBeVisible();
  // Scoped to "main": the header has its own "Log in" link, so the bare locator is ambiguous.
  await expect(page.getByRole("main").getByRole("link", { name: "Log in" })).toBeVisible();
});

test("adding a watch, seeing it listed, then removing it", async ({ page }) => {
  await login(page);
  await page.goto("/watchlist");

  await page.getByLabel("Medicine or manufacturer name to watch").fill("Brivolax");
  await page.getByRole("button", { name: "Watch", exact: true }).click();

  await expect(page).toHaveURL("/watchlist");
  await expect(page.getByText("Brivolax")).toBeVisible();
  await expect(page.getByText("You aren't watching anything yet.")).toHaveCount(0);

  await page.getByRole("button", { name: "Stop watching" }).click();

  await expect(page.getByText("You aren't watching anything yet.")).toBeVisible();
});

test("watching the same term twice shows the backend's own message", async ({ page }) => {
  await login(page);
  await page.goto("/watchlist");

  await page.getByLabel("Medicine or manufacturer name to watch").fill("Calmirex");
  await page.getByRole("button", { name: "Watch", exact: true }).click();
  // Not waitForURL("/watchlist"): we're already there from the goto above, so that would resolve
  // instantly without proving the first add actually landed. Waiting for the watch to actually
  // show up is the real signal that the round trip finished before the second attempt starts.
  await expect(page.getByText("Calmirex")).toBeVisible();
  await page.getByLabel("Medicine or manufacturer name to watch").fill("Calmirex");
  await page.getByRole("button", { name: "Watch", exact: true }).click();

  await expect(page).toHaveURL(/\/watchlist\?error=/);
  await expect(page.getByText("You are already watching that.")).toBeVisible();
});

test("notification history shows what was already sent, linked to a search", async ({ page }) => {
  await login(page);
  await page.goto("/watchlist");

  await expect(page.getByRole("heading", { name: "Notifications sent to you" })).toBeVisible();
  const link = page.getByRole("link", { name: "Zyntophil" });
  await expect(link).toBeVisible();
  await expect(page.getByText(/3 batches in the February 2026 alert/)).toBeVisible();

  await link.click();
  await expect(page).toHaveURL(/\/drugs\/search\?q=Zyntophil/);
});

test("the header's Watchlist link only appears once logged in", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("link", { name: "Watchlist" })).toHaveCount(0);

  await login(page);
  await expect(page.getByRole("link", { name: "Watchlist" })).toBeVisible();
});
