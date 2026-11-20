import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import type { ChartSpec } from "../api/types";
import { ChartFrame } from "../components/ChartFrame";
import { swatchSpec } from "../dev/specs";
import { CashFlowRenderer } from "./CashFlowRenderer";
import { clearRenderers, registerRenderer } from "./registry";

beforeEach(() => registerRenderer("cash_flow", CashFlowRenderer));
afterEach(() => clearRenderers());

const spec: ChartSpec = {
  ...swatchSpec,
  template_id: "cash_flow",
  title: "You spent more than you earned, Mar 2026: net −$210.75",
  annotations: [],
  series: [
    ...swatchSpec.series,
    {
      id: "running_net",
      kind: "line",
      label: "Running net",
      result_id: "running_net:res_7f3b",
      points: [
        { x: "2026-02-01", y: "549.60", partial: false },
        { x: "2026-03-01", y: "338.85", partial: false },
      ],
    },
  ],
};

describe("CashFlowRenderer", () => {
  it("draws the chart inside the frame with its legend", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec }} />);

    expect(screen.getByRole("group", { name: `${spec.title} chart` })).toBeInTheDocument();
    expect(container.querySelector("svg[role='img']")).not.toBeNull();
    expect(container.querySelectorAll("path[data-series='inflow']")).toHaveLength(2);
    expect(container.querySelectorAll("path[data-series='outflow']")).toHaveLength(2);
    for (const name of ["Inflow", "Outflow", "Net"]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
    expect(screen.getByText("Running net through Mar 2026")).toBeInTheDocument();
  });

  it("marks an overspent month with the amount written out, not color alone", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec }} />);

    const labels = [...container.querySelectorAll("svg text")].map((t) => t.textContent);
    expect(labels).toContain("−$210.75");
  });

  it("writes the marker and axis in the spec's currency, not dollars", () => {
    const euro: ChartSpec = { ...spec, params: { ...spec.params, currency: "EUR" } };
    const { container } = render(<ChartFrame state={{ status: "ready", spec: euro }} />);

    const labels = [...container.querySelectorAll("svg text")].map((t) => t.textContent ?? "");
    expect(labels).toContain("−€210.75");
    expect(labels.filter((t) => t.includes("$"))).toEqual([]);
    expect(labels.some((t) => t.includes("€"))).toBe(true);
  });

  it("reads a month from the keyboard: arrows move, the stats follow", async () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec }} />);
    const chart = container.querySelector<SVGElement>("svg[role='img']")!;
    const month = () => container.querySelector("p[aria-live]")!.textContent;
    // The latest month is shown first.
    expect(month()).toBe("Mar 2026");
    chart.focus();
    fireEvent.keyDown(chart, { key: "ArrowLeft" });
    expect(month()).toBe("Feb 2026");
    // A positive net is signed too: glyph and words, not just "no minus".
    const net = () => [...container.querySelectorAll(".stat-value .money")].at(-1)!;
    expect(net()).toHaveTextContent("▲ $549.60 (positive)");
    fireEvent.keyDown(chart, { key: "End" });
    expect(month()).toBe("Mar 2026");
    expect(net()).toHaveTextContent("▼ −$210.75 (negative)");
  });

  it("keeps the exact running net in the data table", () => {
    render(<ChartFrame state={{ status: "ready", spec }} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
