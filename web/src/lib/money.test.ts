import { formatMoney, formatMonth, formatShare, signOf, toNumber } from "./money";

describe("formatMoney", () => {
  it.each([
    ["3200.00", "$3,200.00"],
    ["-210.75", "−$210.75"],
    ["1234567.5", "$1,234,567.50"],
    ["0.07", "$0.07"],
    ["12", "$12.00"],
    ["-0.00", "$0.00"],
  ])("%s -> %s", (input, expected) => {
    expect(formatMoney(input)).toBe(expected);
  });

  it("keeps every digit it was given (no float rounding)", () => {
    expect(formatMoney("9007199254740993.01")).toBe("$9,007,199,254,740,993.01");
    expect(formatMoney("0.123")).toBe("$0.123");
  });

  it("names unknown currencies instead of guessing a symbol", () => {
    expect(formatMoney("5.00", "CHF")).toBe("CHF 5.00");
    expect(formatMoney("5.00", "EUR")).toBe("€5.00");
  });

  it("rejects anything that is not a decimal string", () => {
    expect(() => formatMoney("1e3")).toThrow();
    expect(() => formatMoney("")).toThrow();
    expect(() => formatMoney("$5")).toThrow();
  });
});

describe("signOf", () => {
  it("classifies by value, treating negative zero as zero", () => {
    expect(signOf("-210.75")).toBe("negative");
    expect(signOf("3.00")).toBe("positive");
    expect(signOf("0.00")).toBe("zero");
    expect(signOf("-0.00")).toBe("zero");
  });
});

describe("toNumber", () => {
  it("is for geometry and still validates its input", () => {
    expect(toNumber("-210.75")).toBe(-210.75);
    expect(() => toNumber("abc")).toThrow();
  });
});

describe("formatMonth", () => {
  it("formats the first of the month", () => {
    expect(formatMonth("2026-03-01")).toBe("Mar 2026");
    expect(formatMonth("2025-12-01")).toBe("Dec 2025");
  });
  it("rejects non-dates", () => {
    expect(() => formatMonth("March")).toThrow();
    expect(() => formatMonth("2026-13-01")).toThrow();
  });
});

describe("formatShare", () => {
  it.each([
    ["0.1234", "12.34%"],
    ["0.0098", "0.98%"],
    ["1.0000", "100%"],
    ["0.7377", "73.77%"],
    ["0", "0%"],
    ["-0.05", "−5%"],
    ["1.25", "125%"],
  ])("%s -> %s", (input, expected) => {
    expect(formatShare(input)).toBe(expected);
  });
});
