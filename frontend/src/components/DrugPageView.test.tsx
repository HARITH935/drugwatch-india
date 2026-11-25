import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { DrugPage, Finding } from "@/lib/backend";

import { DrugPageView } from "./DrugPageView";

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

function page(overrides: Partial<DrugPage> = {}): DrugPage {
  return {
    drug: {
      drugId: "d1",
      productName: "Zyntophil Tablets 500 mg",
      genericName: "Zyntophilin",
      dosageForm: "Tablet",
      strengths: ["500 mg"],
      drugClasses: ["Analgesic"],
      findings: 1,
      firstAlertMonth: "2026-03",
      lastAlertMonth: "2026-03",
    },
    findings: [finding()],
    meaning: "This finding applies to one specific batch.",
    disclaimer: "Not medical advice. Data from CDSCO public alerts.",
    ...overrides,
  };
}

describe("DrugPageView", () => {
  it("shows the medicine's name, generic name and dosage form", () => {
    render(<DrugPageView page={page()} />);
    expect(screen.getByRole("heading", { name: "Zyntophil Tablets 500 mg" })).toBeInTheDocument();
    expect(screen.getByText("Zyntophilin")).toBeInTheDocument();
    expect(screen.getByText("Tablet")).toBeInTheDocument();
  });

  it("says 'in <month>' for a single-month history, not a confusing same-month range", () => {
    render(<DrugPageView page={page()} />);
    expect(screen.getByText(/1 batch reported in March 2026\./)).toBeInTheDocument();
  });

  it("says a range when the history spans more than one month", () => {
    render(
      <DrugPageView
        page={page({
          drug: {
            ...page().drug,
            firstAlertMonth: "2025-09",
            lastAlertMonth: "2026-03",
            findings: 2,
          },
        })}
      />,
    );
    expect(screen.getByText(/between September 2025 and March 2026/)).toBeInTheDocument();
  });

  it("renders every finding", () => {
    render(
      <DrugPageView page={page({ findings: [finding(), finding({ batchNumber: "TB-9999" })] })} />,
    );
    expect(screen.getByText("TB-1201")).toBeInTheDocument();
    expect(screen.getByText("TB-9999")).toBeInTheDocument();
  });
});
