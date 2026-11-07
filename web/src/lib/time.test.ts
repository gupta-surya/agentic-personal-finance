import { formatAsOf } from "./time";

describe("formatAsOf", () => {
  it("shows the time in UTC, converting any offset", () => {
    expect(formatAsOf("2026-04-02T12:00:00Z")).toBe("2026-04-02 12:00 UTC");
    expect(formatAsOf("2026-04-02T14:30:00+02:00")).toBe("2026-04-02 12:30 UTC");
  });
  it("leaves something that is not a date as it was", () => {
    expect(formatAsOf("yesterday")).toBe("yesterday");
  });
});
