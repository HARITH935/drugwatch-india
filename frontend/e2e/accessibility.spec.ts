import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// WCAG 2.1 A/AA, the same bar step 1's design tokens were computed against (real relative-
// luminance contrast math, not eyeballed - see docs/adr's design-system notes). Each page gets
// its own test so one failure names exactly which page and rule, rather than one test covering
// the whole site.
const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];

const PAGES: Array<[string, string]> = [
  ["home", "/"],
  ["a flagged batch result", "/batches/search?drug=Zyntophil&batch=TB-1201"],
  ["a not-found batch result", "/batches/search?drug=Unknownmed&batch=ZZ-0000"],
  ["drug search, empty", "/drugs/search"],
  ["drug search, with results", "/drugs/search?q=Zyntophil"],
  ["a drug page", "/drugs/d1"],
  ["a manufacturer page", "/manufacturers/m1"],
  ["a real 404", "/drugs/doesnotexist"],
  ["login", "/login"],
  ["register", "/register"],
  ["register check-email", "/register/check-email"],
  ["a working verification link", "/verify?token=valid-token"],
  ["a failed verification link", "/verify?token=bad-token"],
  ["the watchlist, logged out", "/watchlist"],
  ["dashboards", "/dashboards"],
  ["about & methodology", "/about"],
];

for (const [name, path] of PAGES) {
  test(`${name} has no WCAG 2.1 A/AA violations`, async ({ page }) => {
    await page.goto(path);
    let builder = new AxeBuilder({ page }).withTags(TAGS);
    // Superset's own embedded page, a cross-origin third party this project doesn't control or
    // ship - Playwright's automation access can reach inside it in a way an ordinary browser
    // tab's own script never could, so scanning it here would both fail on someone else's UI and
    // behave differently between a dev machine (real Superset) and CI (nothing at that address).
    if (path === "/dashboards") builder = builder.exclude("iframe");
    const results = await builder.analyze();
    expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
  });
}

// A separate concern from the WCAG checks above, but cheap to verify on every page while
// already visiting each one - found the hard way (PROGRESS.md step 6) that this only reproduces
// under CI's Linux font fallback, never on a Mac, so every page is worth checking here rather
// than trusting that step 0's one example (home.spec.ts) still generalises.
for (const [name, path] of PAGES) {
  test(`${name} has no horizontal overflow`, async ({ page }) => {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBe(0);
  });
}

test("the logged-in watchlist (with a watch and its form) has no WCAG 2.1 A/AA violations", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill("sentinel@example.com");
  await page.getByLabel("Password").fill("a-secret-password-12");
  await page.getByRole("button", { name: "Log in" }).click();
  await page.waitForURL("/");
  await page.goto("/watchlist");

  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
});
