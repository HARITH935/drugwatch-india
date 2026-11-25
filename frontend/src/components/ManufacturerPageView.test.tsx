import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ManufacturerPage } from "@/lib/backend";

import { ManufacturerPageView } from "./ManufacturerPageView";

function page(overrides: Partial<ManufacturerPage> = {}): ManufacturerPage {
  return {
    manufacturer: {
      manufacturerId: "m1",
      name: "Marvex Labs",
      state: "Himachal Pradesh",
      firstAlertMonth: "2026-03",
      lastAlertMonth: "2026-03",
      reportedBatches: 1,
      alertMonths: 1,
      distinctMedicines: 1,
    },
    medicines: [
      {
        drugId: "d1",
        productName: "Zyntophil Tablets 500 mg",
        reportedBatches: 1,
        lastAlertMonth: "2026-03",
      },
    ],
    meaning: "These are batches of this company's medicines that a government laboratory reported.",
    disclaimer: "Not medical advice. Data from CDSCO public alerts.",
    ...overrides,
  };
}

describe("ManufacturerPageView", () => {
  it("shows the company name, state and the reported-batches wording (never 'failures')", () => {
    render(<ManufacturerPageView page={page()} />);
    expect(screen.getByRole("heading", { name: "Marvex Labs" })).toBeInTheDocument();
    expect(screen.getByText("Himachal Pradesh")).toBeInTheDocument();
    expect(screen.getByText(/reported batch across 1 medicine/)).toBeInTheDocument();
    expect(screen.queryByText(/failure/i)).not.toBeInTheDocument();
  });

  it("links each medicine to its drug page", () => {
    render(<ManufacturerPageView page={page()} />);
    expect(screen.getByRole("link", { name: "Zyntophil Tablets 500 mg" })).toHaveAttribute(
      "href",
      "/drugs/d1",
    );
  });

  it("never mentions spurious findings - they carry no manufacturer_id to join on", () => {
    render(<ManufacturerPageView page={page()} />);
    expect(screen.queryByText(/spurious/i)).not.toBeInTheDocument();
  });
});
