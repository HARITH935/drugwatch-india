import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { LatestAlerts } from "@/lib/backend";

import { LatestAlertsSummary } from "./LatestAlertsSummary";

// Invented values (ADR 0003: no real CDSCO rows in git), in the shape the backend really sends.
const DATA: LatestAlerts = {
  alertMonth: "2026-09",
  findings: 330,
  reportingLabs: 48,
  companies: 232,
  mostReportedMedicines: [
    { productName: "Zyntophil Tablets 500 mg", findings: 14 },
    { productName: "Marvexol Syrup", findings: 1 },
  ],
  note: "A busier month usually means more testing, not worse medicine.",
  disclaimer: "Not medical advice. Data from CDSCO public alerts.",
};

describe("LatestAlertsSummary", () => {
  it("names the alert month in words", () => {
    render(<LatestAlertsSummary data={DATA} />);
    expect(screen.getByRole("heading", { name: /September 2026/ })).toBeInTheDocument();
  });

  it("counts batches neutrally, as CLAUDE.md §6 asks", () => {
    const { container } = render(<LatestAlertsSummary data={DATA} />);
    expect(container).toHaveTextContent("330 batches reported as not of standard quality");
    expect(container).toHaveTextContent("1 batch reported");
  });

  it("shows the backend's own caveat about testing effort", () => {
    render(<LatestAlertsSummary data={DATA} />);
    expect(screen.getByText(DATA.note)).toBeInTheDocument();
  });

  it("never uses accusing or reassuring words", () => {
    // CLAUDE.md §6: never call a manufacturer fraudulent, and nothing here may read as "safe".
    const { container } = render(<LatestAlertsSummary data={DATA} />);
    const text = container.textContent?.toLowerCase() ?? "";
    for (const word of ["fraud", "fake", "unsafe", "dangerous", "banned", "safe"]) {
      expect(text).not.toMatch(new RegExp(`\\b${word}\\b`));
    }
  });

  it("says plainly when no data has been loaded, instead of rendering zeros", () => {
    render(<LatestAlertsSummary data={{ ...DATA, alertMonth: null }} />);
    expect(screen.getByText(/No alert data has been loaded yet/)).toBeInTheDocument();
  });
});
