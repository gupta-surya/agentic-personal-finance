import { curveMonotoneX } from "@visx/curve";
import { scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { motion } from "motion/react";
import { useState } from "react";
import type { Series } from "../api/types";
import { categoryColor } from "../lib/colors";
import { formatMoney, formatMonth, toNumber } from "../lib/money";
import { Measure } from "../ui/Measure";
import { EASE_OUT, useCalm } from "../ui/motion";
import { specCurrency } from "./chartData";
import { nearestIndex } from "./primitives";
import type { Renderer } from "./registry";

const H = 52;

/** One category's months as a line. Decorative for screen readers: the row's own cells
 *  carry the figures. Hovering reads a month's exact value. */
function Spark({ series, width, color, onRead }: { series: Series; width: number; color: string; onRead: (i: number | null) => void }) {
  const calm = useCalm();
  const values = series.points.map((p) => toNumber(p.y ?? "0"));
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const y = scaleLinear({ domain: lo === hi ? [lo - 1, hi + 1] : [lo, hi], range: [H - 6, 6] });
  const xs = values.map((_, i) => 4 + (i * (width - 8)) / (values.length - 1));
  const pts = values.map((v, i) => ({ px: xs[i] ?? 0, py: y(v) }));
  const last = pts[pts.length - 1];
  return (
    <svg
      width={width}
      height={H}
      aria-hidden="true"
      style={{ display: "block", overflow: "visible" }}
      onPointerMove={(event) => {
        const box = event.currentTarget.getBoundingClientRect();
        onRead(nearestIndex(xs, event.clientX - box.left));
      }}
      onPointerLeave={() => onRead(null)}
    >
      <LinePath data={pts} x={(p) => p.px} y={(p) => p.py} curve={curveMonotoneX}>
        {({ path }) => (
          <motion.path
            d={path(pts) ?? ""}
            fill="none"
            stroke={color}
            strokeWidth={2}
            strokeLinecap="round"
            initial={calm ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.6, ease: EASE_OUT }}
          />
        )}
      </LinePath>
      {last && <circle cx={last.px} cy={last.py} r={3} fill={color} stroke="var(--surface)" strokeWidth={2} />}
    </svg>
  );
}

function Row({ cells, series, currency }: { cells: (string | null)[]; series: Series | undefined; currency: string }) {
  const [read, setRead] = useState<number | null>(null);
  const [, average, , , change, trend] = cells;
  const name = cells[0] ?? "";
  const color = categoryColor(series?.id ?? name);
  const point = read === null ? undefined : series?.points[read];
  return (
    <li className="mini" data-category={name}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8, flexWrap: "wrap" }}>
        <span style={{ display: "flex", alignItems: "center", gap: 8, fontWeight: 500 }}>
          <i className="key" style={{ background: color }} aria-hidden="true" />
          {name}
        </span>
        <span className="sub" aria-live="polite">
          {point ? (
            <>
              {formatMonth(point.x)} <span style={{ color: "var(--ink)", fontWeight: 500 }}>{point.y == null ? "no data" : formatMoney(point.y, currency)}</span>
            </>
          ) : (
            <>Avg {average} / month</>
          )}
        </span>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          {series && <Measure minHeight={H}>{(width) => <Spark series={series} width={width} color={color} onRead={setRead} />}</Measure>}
        </div>
        {/* The engine's own words and glyph ("▲ Rising"), with the change beside them. */}
        <span className="chip" style={{ minWidth: 112, justifyContent: "center" }}>
          <span>{trend}</span>
          <span style={{ color: "var(--ink-3)" }}>{change}</span>
        </span>
      </div>
    </li>
  );
}

/** Small multiples: one line per category on its own scale, so a small category's
 *  movement is not flattened by rent. The figures are the spec's pre-formatted cells. */
export const CategoryTrendsRenderer: Renderer = ({ spec }) => {
  const currency = specCurrency(spec);
  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0 }}>
      {spec.table.rows.map((row) => (
        <Row key={row[0]} cells={row} series={spec.series.find((s) => s.label === row[0])} currency={currency} />
      ))}
    </ul>
  );
};
