import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { BatchSearchResult, Finding } from "@/lib/backend";

import { BatchResult } from "./BatchResult";

// Invented values (ADR 0003), in the shape BatchSearchResult.java really sends.
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

function result(overrides: Partial<BatchSearchResult> = {}): BatchSearchResult {
  return {
    drug: "Zyntophil",
    batch: "TB-1201",
    outcome: "NOT_FOUND",
    findings: [],
    sameBatchOtherMedicines: [],
    meaning: "This batch does not appear in the CDSCO alerts we hold.",
    disclaimer: "Not medical advice. Data from CDSCO public alerts.",
    ...overrides,
  };
}

describe("BatchResult", () => {
  it("shows the flagged badge and the finding, for a FLAGGED outcome", () => {
    render(<BatchResult result={result({ outcome: "FLAGGED", findings: [finding()] })} />);
    expect(screen.getByText("Reported in a CDSCO alert")).toBeInTheDocument();
    expect(screen.getByText("Zyntophil Tablets 500 mg")).toBeInTheDocument();
  });

  it("shows the not-found badge and the backend's own wording, with no finding cards", () => {
    render(<BatchResult result={result({ meaning: "This batch does not appear anywhere." })} />);
    expect(screen.getByText("No matching alert found")).toBeInTheDocument();
    expect(screen.getByText("This batch does not appear anywhere.")).toBeInTheDocument();
    expect(screen.queryByText(/Batch/)).not.toBeInTheDocument(); // no finding card's field labels
  });

  it("shows the neutral badge for NOT_SEARCHABLE, not a flagged/not-found colour", () => {
    render(<BatchResult result={result({ outcome: "NOT_SEARCHABLE" })} />);
    const badge = screen.getByText("This batch number can't be searched for");
    expect(badge.className).not.toMatch(/flagged-bg|not-found-bg/);
  });

  it("renders cross-matches under a different medicine name even on a NOT_FOUND result", () => {
    // The backend's own reasoning: this is how someone discovers they typed the name differently.
    render(
      <BatchResult
        result={result({
          sameBatchOtherMedicines: [finding({ productName: "A Different Medicine" })],
        })}
      />,
    );
    expect(screen.getByText(/also appears under a different medicine name/)).toBeInTheDocument();
    expect(screen.getByText("A Different Medicine")).toBeInTheDocument();
  });

  it("never uses accusing or reassuring words, in any outcome", () => {
    const outcomes: BatchSearchResult["outcome"][] = ["FLAGGED", "NOT_FOUND", "NOT_SEARCHABLE"];
    for (const outcome of outcomes) {
      const { container, unmount } = render(
        <BatchResult
          result={result({ outcome, findings: outcome === "FLAGGED" ? [finding()] : [] })}
        />,
      );
      const text = container.textContent?.toLowerCase() ?? "";
      for (const word of ["fraud", "fake", "unsafe", "dangerous", "banned", "safe"]) {
        expect(text, `outcome ${outcome} contained "${word}"`).not.toMatch(
          new RegExp(`\\b${word}\\b`),
        );
      }
      unmount();
    }
  });
});
