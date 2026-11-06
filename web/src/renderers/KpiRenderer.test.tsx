import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach } from "vitest";
import type { ChartSpec, Series } from "../api/types";
import { ChartFrame } from "../components/ChartFrame";
import { swatchSpec } from "../dev/specs";
import { registerAllRenderers } from "./index";
import { clearRenderers } from "./registry";

beforeEach(() => registerAllRenderers());
afterEach(() => clearRenderers());

const point = (id: string, label: string, x: string, y: string): Series => ({
  id,
  kind: "point",
  label,
  result_id: "res",
  points: [{ x, y }],
});

function kpi(overrides: { current: string; previous: string; change: string; percent?: string; currency?: string }): ChartSpec {
  return {
    ...swatchSpec,
    template_id: "kpi",
    title: "You spent $2,033.35, Mar 2026",
    params: { currency: overrides.currency ?? "USD" },
    series: [
      point("current", "Mar", "Mar 1, 2026 – Mar 31, 2026", overrides.current),
      point("previous", "Prev", "Jan 29, 2026 – Feb 28, 2026", overrides.previous),
      point("change", "Change", "change", overrides.change),
      ...(overrides.percent ? [point("change_percent", "Change, percent", "change", overrides.percent)] : []),
    ],
    table: { columns: ["Measure", "Value"], rows: [["Mar", "$2,033.35"]] },
  };
}

const show = (spec: ChartSpec) => render(<ChartFrame state={{ status: "ready", spec }} />);

describe("KpiRenderer", () => {
  it("shows the value and a rise as a glyph, words and a signed amount", () => {
    show(kpi({ current: "2033.35", previous: "1947.05", change: "86.30", percent: "0.0443" }));

    expect(screen.getByTestId("kpi-value")).toHaveTextContent("$2,033.35");
    const delta = screen.getByTestId("kpi-delta");
    expect(delta).toHaveTextContent("▲");
    expect(delta).toHaveTextContent("up:");
    expect(delta).toHaveTextContent("+$86.30 (+4.43%) vs Jan 29, 2026 – Feb 28, 2026");
    expect(screen.getByText("Previous period: $1,947.05")).toBeInTheDocument();
  });

  it("shows a fall with a minus sign and a down glyph", () => {
    show(kpi({ current: "1166.65", previous: "1252.95", change: "-86.30", percent: "-0.0689" }));

    const delta = screen.getByTestId("kpi-delta");
    expect(delta).toHaveTextContent("▼");
    expect(delta).toHaveTextContent("down:");
    expect(delta).toHaveTextContent("−$86.30 (−6.89%)");
  });

  it("says n/a, never infinity, when there is no previous value to compare to", () => {
    show(kpi({ current: "40.00", previous: "0.00", change: "40.00" }));

    expect(screen.getByTestId("kpi-delta")).toHaveTextContent("+$40.00 (n/a)");
    expect(screen.getByTestId("kpi-delta").textContent).not.toMatch(/infinity|nan/i);
  });

  it("reports no change without an arrow", () => {
    show(kpi({ current: "50.00", previous: "50.00", change: "0.00", percent: "0.0000" }));

    const delta = screen.getByTestId("kpi-delta");
    expect(delta).toHaveTextContent("unchanged:");
    expect(delta).toHaveTextContent("$0.00 (0%)");
    expect(delta.textContent).not.toMatch(/[▲▼]/);
  });

  it("uses the spec's currency and writes a negative value with its sign", () => {
    show(kpi({ current: "-300.00", previous: "100.00", change: "-400.00", percent: "-4.0000", currency: "EUR" }));

    expect(screen.getByTestId("kpi-value")).toHaveTextContent("−€300.00");
    expect(screen.getByTestId("kpi-delta")).toHaveTextContent("−€400.00 (−400%)");
  });

  it("keeps the exact table", () => {
    show(kpi({ current: "2033.35", previous: "1947.05", change: "86.30", percent: "0.0443" }));
    expect(screen.getByRole("table")).toHaveTextContent("$2,033.35");
  });
});
