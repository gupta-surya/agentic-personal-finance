import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import type { ChartSpec, Series } from "../api/types";
import { ChartFrame } from "../components/ChartFrame";
import { swatchSpec } from "../fixtures/specs";
import { clearRenderers } from "./registry";
import { registerAllRenderers } from "./index";
import { monthRange } from "./chartData";

beforeEach(() => registerAllRenderers());
afterEach(() => clearRenderers());

const bars = (ids: [string, string][]): Series[] =>
  ids.map(([id, label]) => ({
    id,
    kind: "bar",
    label,
    result_id: "res_1",
    points: [
      { x: "2026-03-01", y: "366.20" },
      { x: "2026-05-01", y: "10.00" }, // April has no spend: a gap, not a zero
    ],
  }));

const overTime: ChartSpec = {
  ...swatchSpec,
  template_id: "spend_over_time",
  title: "Spending by category, Mar 2026 – May 2026",
  period: { preset: "custom", start: "2026-03-01", end: "2026-06-01", label: "Mar 1, 2026 – May 31, 2026" },
  params: { currency: "EUR" },
  series: bars([
    ["category:groceries", "Groceries"],
    ["category:rent", "Rent"],
    ["everything_else", "Everything else"],
  ]),
  table: { columns: ["Month", "Groceries"], rows: [["Mar 2026", "€366.20"]] },
};

const breakdown: ChartSpec = {
  ...swatchSpec,
  template_id: "spend_breakdown",
  title: "Rent took the biggest share of spending, 73.77%, Mar 2026",
  params: { currency: "USD" },
  series: [
    {
      id: "amount",
      kind: "bar",
      label: "Spend",
      result_id: "res_1",
      points: [
        { x: "Rent", y: "1500.00" },
        { x: "Groceries", y: "-50.00" },
      ],
    },
    {
      id: "share",
      kind: "point",
      label: "Share of total",
      result_id: "res_1",
      points: [
        { x: "Rent", y: "0.7377" },
        { x: "Groceries", y: "-0.0245" },
      ],
    },
  ],
  table: { columns: ["Category", "Spend", "Share"], rows: [["Rent", "$1,500.00", "73.77%"]] },
};

describe("monthRange", () => {
  it("covers every month of a period, end exclusive", () => {
    expect(monthRange("2026-03-01", "2026-06-01")).toEqual(["2026-03-01", "2026-04-01", "2026-05-01"]);
    expect(monthRange("2025-11-01", "2026-02-01")).toEqual(["2025-11-01", "2025-12-01", "2026-01-01"]);
  });
  it("includes the current partial month when the end is mid-month", () => {
    expect(monthRange("2026-10-01", "2026-10-26")).toEqual(["2026-10-01"]);
  });
});

describe("SpendOverTimeRenderer", () => {
  it("draws a stacked chart with one legend entry per series", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: overTime }} />);

    expect(container.querySelector(".recharts-wrapper")).not.toBeNull();
    for (const label of ["Groceries", "Rent", "Everything else"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("labels the y axis in the spec's currency", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: overTime }} />);
    const texts = [...container.querySelectorAll("svg text")].map((t) => t.textContent ?? "");

    expect(texts.some((t) => t.includes("€"))).toBe(true);
    expect(texts.filter((t) => t.includes("$"))).toEqual([]);
  });

  it("uses lines when there are one or two series", () => {
    const lines: ChartSpec = { ...overTime, series: overTime.series.slice(0, 2).map((s) => ({ ...s, kind: "line" })) };
    const { container } = render(<ChartFrame state={{ status: "ready", spec: lines }} />);

    expect(container.querySelector(".recharts-line")).not.toBeNull();
    expect(container.querySelector(".recharts-bar")).toBeNull();
  });
});

describe("SpendBreakdownRenderer", () => {
  it("writes each amount and share out, marking a negative group without color alone", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: breakdown }} />);
    const labels = [...container.querySelectorAll("svg text")].map((t) => t.textContent ?? "");

    expect(labels).toContain("$1,500.00 · 73.77%");
    expect(labels).toContain("▼ −$50.00 · −2.45%");
  });

  it("omits the donut when a group is negative and shows it for a few positive groups", () => {
    const { container: negative } = render(<ChartFrame state={{ status: "ready", spec: breakdown }} />);
    expect(negative.querySelector(".recharts-pie")).toBeNull();

    const positive: ChartSpec = {
      ...breakdown,
      series: breakdown.series.map((s) => ({
        ...s,
        points: s.points.map((p) => (p.y?.startsWith("-") ? { ...p, y: p.y.slice(1) } : p)),
      })),
    };
    const { container } = render(<ChartFrame state={{ status: "ready", spec: positive }} />);
    const pie = container.querySelector(".recharts-pie");
    expect(pie).not.toBeNull();
    // Decorative: inert, so it takes neither focus nor a screen reader's attention.
    expect(pie?.closest("[inert]")).not.toBeNull();
  });

  it("keeps the exact table", () => {
    render(<ChartFrame state={{ status: "ready", spec: breakdown }} />);
    expect(screen.getByRole("table")).toHaveTextContent("73.77%");
  });
});
