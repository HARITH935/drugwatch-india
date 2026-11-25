import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RiskResult } from "@/lib/backend";

import { RiskScoreCard } from "./RiskScoreCard";

function scored(overrides: Partial<RiskResult> = {}): RiskResult {
  return {
    manufacturerId: "m1",
    name: "Marvex Labs",
    available: true,
    score: 0.42,
    featuresAsOfMonth: "2026-09",
    modelHasSeenThisCompany: true,
    explanation: ["Mainly batches reported in the last 24 months raises it."],
    accuracyNote: "The model was trained on this company's earlier history.",
    meaning: "Reflects reporting history, not quality.",
    disclaimer: "Not medical advice. Data from CDSCO public alerts.",
    ...overrides,
  };
}

describe("RiskScoreCard", () => {
  it("shows the score as a percentage, with the explanation", () => {
    render(<RiskScoreCard result={scored()} />);
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText(/last 24 months/)).toBeInTheDocument();
  });

  // CLAUDE.md §6: "The risk score reflects reporting history, not true quality. Say so wherever
  // it is shown." This is the structural test for that rule: it is impossible to get a score
  // number out of this component without `meaning` appearing in the exact same render.
  it("never renders a score without the caveat alongside it", () => {
    render(<RiskScoreCard result={scored()} />);
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("Reflects reporting history, not quality.")).toBeInTheDocument();
  });

  it("still shows the caveat, with no score, when the company isn't scoreable", () => {
    render(
      <RiskScoreCard
        result={scored({
          available: false,
          score: null,
          accuracyNote: null,
          explanation: [],
          meaning: "This company has no reported findings in the archive.",
        })}
      />,
    );
    expect(screen.queryByText(/%/)).not.toBeInTheDocument();
    expect(
      screen.getByText("This company has no reported findings in the archive."),
    ).toBeInTheDocument();
  });

  it("shows the new-to-the-model caution, distinct from the seen-in-training note", () => {
    render(
      <RiskScoreCard
        result={scored({
          modelHasSeenThisCompany: false,
          accuracyNote: "Treat this number with more caution than usual.",
        })}
      />,
    );
    expect(screen.getByText(/more caution than usual/)).toBeInTheDocument();
  });
});
