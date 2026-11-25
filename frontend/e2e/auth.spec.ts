import { expect, test } from "@playwright/test";

// Credentials the stub backend accepts - see e2e/stub-backend.mjs's TEST_ACCOUNT.
const EMAIL = "sentinel@example.com";
const PASSWORD = "a-secret-password-12";

test("registering shows the same message regardless of what happened", async ({ page }) => {
  await page.goto("/register");
  await page.getByLabel("Email").fill("someone@example.com");
  await page.getByLabel("Password").fill("a-long-enough-password");
  await page.getByRole("button", { name: "Register" }).click();

  await expect(page).toHaveURL(/\/register\/check-email$/);
  await expect(page.getByText(/If that address can have an account/)).toBeVisible();
});

test("logging in with the wrong password shows a generic error", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("not-the-right-password");
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page).toHaveURL(/\/login\?error=invalid$/);
  await expect(page.getByText("Email or password is not correct.")).toBeVisible();
  // Still logged out: the header offers to log in, not to log out.
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
});

test("logging in, then out, round-trips the header's session state", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Log in" }).click();

  await expect(page).toHaveURL("/");
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Log in" })).toHaveCount(0);

  // A page navigation while still logged in keeps showing the logged-in header - the session
  // lives in a cookie, not in client-side state that a fresh page load would lose.
  await page.goto("/drugs/search");
  await expect(page.getByRole("button", { name: "Log out" })).toBeVisible();

  await page.getByRole("button", { name: "Log out" }).click();
  await expect(page).toHaveURL("/");
  await expect(page.getByRole("link", { name: "Log in" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);
});

test("a working verification link confirms the address", async ({ page }) => {
  await page.goto("/verify?token=valid-token");
  await expect(page.getByRole("heading", { name: "Email confirmed" })).toBeVisible();
});

test("an expired or already-used verification link says so, not a crash", async ({ page }) => {
  await page.goto("/verify?token=already-used");
  await expect(page.getByRole("heading", { name: "That link didn't work" })).toBeVisible();
});
