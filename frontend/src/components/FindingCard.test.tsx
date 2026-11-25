import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Finding } from "@/lib/backend";

import { FindingCard } from "./FindingCard";

// Invented values (ADR 0003: no real CDSCO text in git), in the shape Finding.java really sends.
function finding(overrides: Partial<Finding> = {}): Finding {
  return {
    batchNumber: "TB-1201",
    alertMonth: "2026-03",
    productName: "Zyntophil Tablets 500 mg",
    failureReason: "Assay",
    failureCategories: ["Assay"],
    spurious: false,
    nameOnPack: null,
    manufacturerId: "m1",
    manufacturerName: "Marvex Labs",
    reportedBy: "DTL, Shimla",
    labType: "State",
    sourceUrl: "https://cdsco.example.invalid/alert.pdf",
    ...overrides,
  };
}

describe("FindingCard", () => {
  it("always shows the batch number, alert month and a source link (CLAUDE.md §6)", () => {
    render(<FindingCard finding={finding()} />);
    expect(screen.getByText("TB-1201")).toBeInTheDocument();
    expect(screen.getByText("March 2026")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /original CDSCO document/ })).toHaveAttribute(
      "href",
      "https://cdsco.example.invalid/alert.pdf",
    );
  });

  it("shows the manufacturer for an ordinary finding", () => {
    render(<FindingCard finding={finding()} />);
    expect(screen.getByText("Marvex Labs")).toBeInTheDocument();
  });

  it("never shows a manufacturer for a spurious finding, even if the data says otherwise", () => {
    // Finding.java's constructor refuses this combination server-side, but the COMPONENT must
    // refuse it too, independently - a render that trusted the backend's invariant and skipped
    // its own check would be one bad row away from accusing a counterfeiting victim.
    render(
      <FindingCard
        finding={finding({
          spurious: true,
          manufacturerName: "Should never render",
          nameOnPack: "Zyntophil",
        })}
      />,
    );
    expect(screen.queryByText("Should never render")).not.toBeInTheDocument();
    expect(screen.getByText("Zyntophil")).toBeInTheDocument(); // the name on the pack, instead
    expect(screen.getByText(/spurious \(counterfeit\)/)).toBeInTheDocument();
  });

  it("omits the manufacturer line rather than printing an empty one when it isn't null but isn't stated", () => {
    render(<FindingCard finding={finding({ manufacturerName: null })} />);
    expect(screen.getByText("Not stated in the alert")).toBeInTheDocument();
  });

  it("preserves line breaks CDSCO printed in a multi-line product name", () => {
    const { container } = render(
      <FindingCard finding={finding({ productName: "Zyntophil\nTablets 500 mg" })} />,
    );
    expect(container.querySelector(".whitespace-pre-line")).toHaveTextContent("Zyntophil");
  });
});
