import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Badge } from "./Badge";

// CLAUDE.md §6: "not found" must never read as "safe". There is no "success"/"safe" variant in
// Badge.tsx at all - this test guards that absence directly, by name, so a future PR that adds
// one back (e.g. "it would help UX to show a green tick for a clean result") fails here first.
describe("Badge", () => {
  it("has no success/safe variant", () => {
    // @ts-expect-error - "success" is not a valid Variant; this line should not type-check
    const attempt = () => render(<Badge variant="success">ok</Badge>);
    expect(attempt).toBeDefined(); // the real check is the ts-expect-error above
  });

  it("flagged and notFound use different hues, neither of them green", () => {
    const { container: flagged } = render(<Badge variant="flagged">Reported</Badge>);
    const { container: notFound } = render(<Badge variant="notFound">Not found</Badge>);

    const flaggedClasses = flagged.querySelector("span")?.className ?? "";
    const notFoundClasses = notFound.querySelector("span")?.className ?? "";

    expect(flaggedClasses).toContain("flagged-bg");
    expect(notFoundClasses).toContain("not-found-bg");
    expect(flaggedClasses).not.toBe(notFoundClasses);
    for (const classes of [flaggedClasses, notFoundClasses]) {
      expect(classes).not.toMatch(/\bgreen\b/);
      expect(classes).not.toMatch(/\bsuccess\b/);
    }
  });
});
