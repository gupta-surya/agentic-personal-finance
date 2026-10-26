import type { ChartSpec, Series } from "../api/types";
import { formatMoney, toNumber } from "../lib/money";

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

/** The spec's currency (the builder echoes it in params); USD if absent. */
export function specCurrency(spec: ChartSpec): string {
  const currency = spec.params.currency;
  return typeof currency === "string" ? currency : "USD";
}

/** An axis tick label. Ticks are positions the chart library picked on its scale, not
 *  figures about the data, so they are only formatted: whole units, in the spec's
 *  currency, with no division or rounding. */
export function axisMoney(value: number, currency = "USD"): string {
  const text = Number.isInteger(value) ? String(value) : value.toFixed(2);
  return formatMoney(text, currency).replace(/\.00$/, "");
}
