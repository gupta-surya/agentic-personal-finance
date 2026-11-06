import { render, screen, within } from "@testing-library/react";
import axe from "axe-core";
import { afterEach, beforeEach } from "vitest";
import type { ChartSpec } from "../api/types";
import { ChartFrame } from "../components/ChartFrame";
import { swatchSpec } from "../dev/specs";
import { registerAllRenderers } from "./index";
import { clearRenderers } from "./registry";

beforeEach(() => registerAllRenderers());
afterEach(() => clearRenderers());

const months = ["2026-04-01", "2026-05-01", "2026-06-01", "2026-07-01"];

const spec: ChartSpec = {
  ...swatchSpec,
  template_id: "category_trends",
  title: "Category spending trends, Apr 2026 – Jul 2026",
  series: [
    { id: "category:dining", kind: "line", label: "Dining", result_id: "r", points: months.map((x, i) => ({ x, y: ["100", "100", "150", "150"][i]! })) },
    { id: "category:rent", kind: "line", label: "Rent", result_id: "r", points: months.map((x) => ({ x, y: "1500.00" })) },
  ],
  table: {
    columns: ["Category", "Average per month", "Lowest month", "Highest month", "Change", "Trend"],
    rows: [
      ["Dining", "$125.00", "$100.00", "$150.00", "+50%", "▲ Rising"],
      ["Rent", "$1,500.00", "$1,500.00", "$1,500.00", "0%", "– Flat"],
    ],
  },
};

const show = (s: ChartSpec) => render(<ChartFrame state={{ status: "ready", spec: s }} />);

describe("CategoryTrendsRenderer", () => {
  it("shows each category's figures and trend as written text, never color alone", () => {
    show(spec);

    const dining = screen.getAllByRole("row").find((r) => within(r).queryByText("Dining"))!;
    for (const text of ["$125.00", "$100.00", "$150.00", "+50%", "▲ Rising"]) {
      expect(within(dining).getByText(text)).toBeInTheDocument();
    }
    expect(screen.getAllByText("– Flat").length).toBeGreaterThan(0);
  });

  it("draws one decorative sparkline per category, hidden from assistive tech", () => {
    const { container } = show(spec);
    const lines = container.querySelectorAll("svg[aria-hidden='true'] polyline");

    expect(lines).toHaveLength(2);
    expect(container.querySelectorAll("svg[aria-hidden='true']")).toHaveLength(2);
  });

  it("draws a flat series mid-height without dividing by zero", () => {
    const { container } = show(spec);
    const flat = container.querySelectorAll("polyline")[1]!; // Rent: all 1500.00
    const ys = flat.getAttribute("points")!.split(" ").map((p) => Number(p.split(",")[1]));

    expect(ys.every((y) => Number.isFinite(y))).toBe(true);
    expect(new Set(ys).size).toBe(1);
  });

  it("has no axe violations", async () => {
    const { container } = show(spec);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
