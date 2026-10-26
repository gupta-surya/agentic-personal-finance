import type { ChartSpec, Series } from "../api/types";
import { toNumber } from "../lib/money";

/** One x position across every series: numbers for placing marks, the original strings
 *  for labels and tooltips. This is the toChartRows convention. */
export interface Row {
  x: string;
  values: Record<string, number>;
  strings: Record<string, string>;
}

export function pivotSeries(series: Series[]): Row[] {
  const byX = new Map<string, Row>();
  for (const s of series) {
    for (const p of s.points) {
      const row = byX.get(p.x) ?? { x: p.x, values: {}, strings: {} };
      if (p.y != null) {
        row.values[s.id] = toNumber(p.y);
        row.strings[s.id] = p.y;
      }
      byX.set(p.x, row);
    }
  }
  return [...byX.values()].sort((a, b) => a.x.localeCompare(b.x));
}

export function seriesLabel(spec: ChartSpec, id: string): string {
  return spec.series.find((s) => s.id === id)?.label ?? id;
}

/** Compact axis labels. Axis ticks are scale marks, not figures about the data. */
export function axisMoney(value: number): string {
  const sign = value < 0 ? "−" : "";
  const abs = Math.abs(value);
  return `${sign}$${abs >= 1000 ? `${+(abs / 1000).toFixed(1)}k` : abs}`;
}
