import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DISCLAIMER, Disclaimer } from "./Disclaimer";

describe("Disclaimer", () => {
  it("is exactly the wording CLAUDE.md §6 requires", () => {
    // Also the backend's PublicNotes.DISCLAIMER. A reworded copy here would be the one that drifts.
    expect(DISCLAIMER).toBe("Not medical advice. Data from CDSCO public alerts.");
  });

  it("renders that text", () => {
    render(<Disclaimer />);
    expect(screen.getByText(DISCLAIMER)).toBeInTheDocument();
  });
});
