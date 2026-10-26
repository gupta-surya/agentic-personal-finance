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

/** Every month a period covers, as "YYYY-MM-01" (`end` is exclusive), so a chart can lay
 *  out a continuous axis and show a month with no data as a gap, not skip it. */
export function monthRange(startIso: string, endIso: string): string[] {
  const parse = (iso: string) => {
    const match = /^(\d{4})-(\d{2})-\d{2}$/.exec(iso);
    if (!match) throw new Error(`not an ISO date: ${JSON.stringify(iso)}`);
    return Number(match[1]) * 12 + Number(match[2]) - 1;
  };
  const last = parse(endIso) - (endIso.endsWith("-01") ? 1 : 0); // exclusive end
  const months: string[] = [];
  for (let m = parse(startIso); m <= last; m += 1) {
    months.push(`${Math.floor(m / 12)}-${String((m % 12) + 1).padStart(2, "0")}-01`);
  }
  return months;
}

/** Entry animations are off for people who ask the OS for reduced motion. */
export function animationsOn(): boolean {
  return !(typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches);
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
