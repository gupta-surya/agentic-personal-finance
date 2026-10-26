import type { Series } from "../api/types";
import { axisMoney, pivotSeries } from "./chartData";

const series = (id: string, ys: [string, string | null][]): Series => ({
  id,
  kind: "line",
  label: id,
  result_id: "r",
  points: ys.map(([x, y]) => ({ x, y })),
});

describe("pivotSeries", () => {
  it("joins series on x, keeps the original strings, and sorts by x", () => {
    const rows = pivotSeries([
      series("net", [["2026-03-01", "-210.75"], ["2026-02-01", "549.60"]]),
      series("inflow", [["2026-02-01", "3200.00"], ["2026-03-01", "3200.00"]]),
    ]);

    expect(rows.map((r) => r.x)).toEqual(["2026-02-01", "2026-03-01"]);
    expect(rows[1]?.values).toEqual({ net: -210.75, inflow: 3200 });
    expect(rows[1]?.strings).toEqual({ net: "-210.75", inflow: "3200.00" });
  });

  it("leaves a series out of a row it has no value for", () => {
    const rows = pivotSeries([series("a", [["2026-02-01", "1.00"]]), series("b", [["2026-03-01", null]])]);
    expect(rows[0]?.values).toEqual({ a: 1 });
    expect(rows[1]?.values).toEqual({});
  });
});

describe("axisMoney", () => {
  it.each([
    [0, "$0"],
    [500, "$500"],
    [1500, "$1.5k"],
    [-2000, "−$2k"],
  ])("%s -> %s", (value, expected) => {
    expect(axisMoney(value)).toBe(expected);
  });
});
