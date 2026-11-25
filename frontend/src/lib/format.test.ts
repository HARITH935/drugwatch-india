import { describe, expect, it } from "vitest";

import { batches, formatAlertMonth, formatCount } from "./format";

describe("formatAlertMonth", () => {
  it("turns an alert month into words", () => {
    expect(formatAlertMonth("2026-09")).toBe("September 2026");
  });

  it("does not slip into the previous month in a time zone west of UTC", () => {
    // The trap: new Date("2026-01-01") in a negative-offset zone renders as December 2025.
    expect(formatAlertMonth("2026-01")).toBe("January 2026");
  });

  it("leaves anything that isn't a month alone rather than guessing", () => {
    expect(formatAlertMonth("2026-13")).toBe("2026-13");
    expect(formatAlertMonth("not a month")).toBe("not a month");
  });
});

describe("counts", () => {
  it("uses Indian digit grouping", () => {
    expect(formatCount(7126)).toBe("7,126");
    expect(formatCount(150000)).toBe("1,50,000");
  });

  it("says batch for one and batches otherwise", () => {
    expect(batches(1)).toBe("1 batch");
    expect(batches(330)).toBe("330 batches");
    expect(batches(0)).toBe("0 batches");
  });
});
