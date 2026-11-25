import { expect, test } from "@playwright/test";

// The actual Superset embed can't be exercised here - there's no real Superset in CI, and the
// one on this Mac would reject the stub's fake guest token anyway. What's tested is everything
// up to that boundary: the tab list, switching tabs, and the Route Handler's own proxying -
// verified manually against the live backend AND a real Superset instead (see PROGRESS.md).

test("lists the backend's allowlisted dashboards as tabs, labelled in plain English", async ({
  page,
}) => {
  await page.goto("/dashboards");

  await expect(page.getByRole("tab", { name: "By state" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Manufacturer reporting" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Spurious reports" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Drug classes" })).toBeVisible();
});

test("the first tab starts selected, and clicking another one selects it instead", async ({
  page,
}) => {
  await page.goto("/dashboards");

  const first = page.getByRole("tab", { name: "Drug classes" }); // alphabetically first key
  const states = page.getByRole("tab", { name: "By state" });
  await expect(first).toHaveAttribute("aria-selected", "true");
  await expect(states).toHaveAttribute("aria-selected", "false");

  await states.click();

  await expect(states).toHaveAttribute("aria-selected", "true");
  await expect(first).toHaveAttribute("aria-selected", "false");
});

test("the guest-token Route Handler proxies a real allowlisted key to the backend's shape", async ({
  page,
}) => {
  await page.goto("/dashboards"); // the route needs a built app running, not a bare request context
  const response = await page.request.post("/api/dashboards/states/guest-token");

  expect(response.status()).toBe(200);
  const body = await response.json();
  expect(body).toMatchObject({ dashboard: "states", dashboardId: "stub-uuid-states" });
  expect(body.token).toBeTruthy();
});

test("the guest-token Route Handler turns an unlisted key into the backend's 404, not a 500", async ({
  page,
}) => {
  await page.goto("/dashboards");
  const response = await page.request.post("/api/dashboards/some-internal-dashboard/guest-token");

  expect(response.status()).toBe(404);
});
