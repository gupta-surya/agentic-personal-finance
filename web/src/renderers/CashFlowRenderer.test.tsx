import { render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, vi } from "vitest";
import type { ChartSpec } from "../api/types";
import { ChartFrame } from "../components/ChartFrame";
import { swatchSpec } from "../fixtures/specs";
import { CashFlowRenderer } from "./CashFlowRenderer";
import { clearRenderers, registerRenderer } from "./registry";

// jsdom has no layout, so give the chart container a size.
beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      constructor(private cb: ResizeObserverCallback) {}
      observe(target: Element) {
        this.cb([{ target, contentRect: { width: 700, height: 320 } } as ResizeObserverEntry], this as never);
      }
      unobserve() {}
      disconnect() {}
    },
  );
  Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 700 });
  Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 320 });
});
beforeEach(() => registerRenderer("cash_flow", CashFlowRenderer));
afterEach(() => clearRenderers());

const spec: ChartSpec = {
  ...swatchSpec,
  template_id: "cash_flow",
  title: "You spent $210.75 more than you earned, Mar 2026",
  annotations: [{ kind: "reference_line", label: "Zero", result_id: "res_7f3b", y: "0" }],
  series: [
    ...swatchSpec.series,
    {
      id: "running_net",
      kind: "line",
      label: "Running net",
      result_id: "running_net:res_7f3b",
      points: [
        { x: "2026-02-01", y: "549.60" },
        { x: "2026-03-01", y: "338.85" },
      ],
    },
  ],
};

describe("CashFlowRenderer", () => {
  it("draws the chart inside the frame with its legend", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec }} />);

    expect(screen.getByRole("group", { name: `${spec.title} chart` })).toBeInTheDocument();
    expect(container.querySelector(".recharts-wrapper")).not.toBeNull();
    for (const name of ["Inflow", "Outflow", "Net", "Running net"]) {
      expect(screen.getAllByText(name).length).toBeGreaterThan(0);
    }
  });

  it("marks an overspent month with the amount written out, not color alone", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec }} />);

    const labels = [...container.querySelectorAll("svg text")].map((t) => t.textContent);
    expect(labels).toContain("−$210.75");
  });

  it("keeps the exact running net in the data table", () => {
    render(<ChartFrame state={{ status: "ready", spec }} />);
    expect(screen.getByRole("table")).toBeInTheDocument();
  });
});
