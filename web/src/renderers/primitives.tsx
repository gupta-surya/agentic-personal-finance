import type { ReactNode } from "react";
import { formatMonth } from "../lib/money";
import { axisMoney } from "./chartData";

// Small drawing helpers shared by the renderers. Geometry only: numbers here are pixel
// positions or scale ticks, never money shown to anyone.

/** A bar from `y0` (the zero line) to `y1` with 4px rounded data-end and a square base. */
export function barPath(x: number, width: number, y0: number, y1: number, radius = 4): string {
  const height = Math.abs(y1 - y0);
  const r = Math.min(radius, height, width / 2);
  if (height === 0) return `M${x},${y0} H${x + width} Z`;
  if (y1 < y0) {
    return `M${x},${y0} V${y1 + r} Q${x},${y1} ${x + r},${y1} H${x + width - r} Q${x + width},${y1} ${x + width},${y1 + r} V${y0} Z`;
  }
  return `M${x},${y0} V${y1 - r} Q${x},${y1} ${x + r},${y1} H${x + width - r} Q${x + width},${y1} ${x + width},${y1 - r} V${y0} Z`;
}

/** Horizontal gridlines with money tick labels on the right. Ticks are positions the
 *  scale picked, formatted only (see `axisMoney`). */
export function GridY({
  ticks,
  y,
  width,
  currency,
  labelX,
}: {
  ticks: number[];
  y: (value: number) => number;
  width: number;
  currency: string;
  labelX?: number;
}) {
  return (
    <g aria-hidden="true">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={0} x2={width} y1={y(t)} y2={y(t)} stroke={t === 0 ? "var(--line-strong)" : "var(--line)"} />
          <text x={labelX ?? width + 8} y={y(t) + 4} fontSize={11} fill="var(--ink-3)">
            {axisMoney(t, currency)}
          </text>
        </g>
      ))}
    </g>
  );
}

/** "2026-04-01" -> "Apr"; January and the first month carry the year ("Jan ’26"). */
export function monthTick(iso: string, first: boolean): string {
  const label = formatMonth(iso); // "Apr 2026"
  const [month, year] = label.split(" ");
  return first || month === "Jan" ? `${month} ’${(year ?? "").slice(2)}` : (month ?? label);
}

/** Every `step`-th label, so labels never collide: about 48px per label. */
export function labelStep(count: number, innerWidth: number): number {
  const fit = Math.max(1, Math.floor(innerWidth / 48));
  return Math.max(1, Math.ceil(count / fit));
}

/** A floating readout next to the pointer or the focused mark. */
export function Tip({ x, y, width, children }: { x: number; y: number; width: number; children: ReactNode }) {
  const left = Math.min(Math.max(0, x + 14), Math.max(0, width - 190));
  return (
    <div className="tip" style={{ left, top: y }} role="presentation">
      {children}
    </div>
  );
}

export function TipRow({ swatch, label, children }: { swatch?: string; label: string; children: ReactNode }) {
  return (
    <div className="tip-row">
      <span className="tip-label">
        {swatch && <i className="key" style={{ background: swatch, width: 8, height: 8, borderRadius: 2 }} />}
        {label}
      </span>
      <span className="tip-value">{children}</span>
    </div>
  );
}

/** Nearest index along x for a pointer: geometry only. */
export function nearestIndex(xs: number[], px: number): number {
  let best = 0;
  xs.forEach((x, i) => {
    if (Math.abs(x - px) < Math.abs((xs[best] ?? 0) - px)) best = i;
  });
  return best;
}

/** Arrow keys step through months; Home and End jump. Returns the new index or null. */
export function stepFor(key: string, index: number, count: number): number | null {
  if (key === "ArrowLeft") return Math.max(0, index - 1);
  if (key === "ArrowRight") return Math.min(count - 1, index + 1);
  if (key === "Home") return 0;
  if (key === "End") return count - 1;
  return null;
}
