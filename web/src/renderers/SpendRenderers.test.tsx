import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import type { ChartSpec, Series } from "../api/types";
import { ChartFrame } from "../components/ChartFrame";
import { swatchSpec } from "../dev/specs";
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
      { x: "2026-03-01", y: "366.20", partial: false },
      { x: "2026-05-01", y: "10.00", partial: false }, // April has no spend: a gap, not a zero
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
        { x: "Rent", y: "1500.00", partial: false },
        { x: "Groceries", y: "-50.00", partial: false },
      ],
    },
    {
      id: "share",
      kind: "point",
      label: "Share of total",
      result_id: "res_1",
      points: [
        { x: "Rent", y: "0.7377", partial: false },
        { x: "Groceries", y: "-0.0245", partial: false },
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

    expect(container.querySelector("svg[role='img']")).not.toBeNull();
    const legend = screen.getByRole("list", { name: "Categories" });
    for (const label of ["Groceries", "Rent", "Everything else"]) {
      expect(within(legend).getByText(label)).toBeInTheDocument();
    }
    // Three months on the axis; April has no spend, so it has no bar (a gap, not a zero).
    const months = container.querySelectorAll("g[data-kind='bar']");
    expect(months).toHaveLength(3);
    expect(months[1]!.querySelectorAll("path")).toHaveLength(0);
    expect(months[0]!.querySelectorAll("path")).toHaveLength(3);
  });

  it("keeps a category's color whatever its position, and greys the folded bucket", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: overTime }} />);
    const fill = (id: string) => container.querySelector(`path[data-series='${id}']`)!.getAttribute("fill");

    expect(fill("category:groceries")).toBe("var(--series-3)");
    expect(fill("category:rent")).toBe("var(--series-1)");
    expect(fill("everything_else")).toBe("var(--series-neutral)");
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

    expect(container.querySelectorAll("g[data-kind='line']")).toHaveLength(2);
    expect(container.querySelector("g[data-kind='bar']")).toBeNull();
  });

  it("reads a month in a tooltip from the keyboard, with exact amounts", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: overTime }} />);
    const chart = container.querySelector<SVGElement>("svg[role='img']")!;
    fireEvent.keyDown(chart, { key: "Home" });

    const tip = container.querySelector(".tip")!;
    expect(tip).toHaveTextContent("Mar 2026");
    expect(tip).toHaveTextContent("Groceries€366.20");
    fireEvent.keyDown(chart, { key: "ArrowRight" });
    expect(container.querySelector(".tip")).toHaveTextContent("Apr 2026No spending");
  });
});

describe("SpendBreakdownRenderer", () => {
  it("writes each amount and share out, marking a negative group without color alone", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: breakdown }} />);
    const row = (label: string) => container.querySelector<HTMLElement>(`li[data-group='${label}']`)!;

    expect(row("Rent")).toHaveTextContent("Rent$1,500.0073.77%");
    expect(row("Groceries")).toHaveTextContent("▼ −$50.00");
    expect(row("Groceries")).toHaveTextContent("−2.45%");
    expect(within(row("Groceries")).getByText(/more refunded than spent/)).toHaveClass("sr-only");
  });

  it("leaves a negative group out of the proportion strip, which is decorative", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: breakdown }} />);
    const strip = container.querySelector(".seg")!;

    expect(strip).toHaveAttribute("aria-hidden", "true");
    expect(strip.querySelectorAll("i")).toHaveLength(1); // Rent only
  });

  it("keeps the exact table", () => {
    render(<ChartFrame state={{ status: "ready", spec: breakdown }} />);
    expect(screen.getByRole("table")).toHaveTextContent("73.77%");
  });
});
