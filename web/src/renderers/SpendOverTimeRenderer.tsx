import { curveMonotoneX } from "@visx/curve";
import { scaleBand, scaleLinear } from "@visx/scale";
import { LinePath } from "@visx/shape";
import { motion } from "motion/react";
import { useState } from "react";
import { Money } from "../components/Money";
import { categoryColor } from "../lib/colors";
import { formatMonth } from "../lib/money";
import { Measure } from "../ui/Measure";
import { EASE_OUT, SPRING, useCalm } from "../ui/motion";
import { monthRange, pivotSeries, specCurrency, type Row } from "./chartData";
import { barPath, GridY, labelStep, monthTick, nearestIndex, stepFor, Tip, TipRow } from "./primitives";
import type { Renderer } from "./registry";

const H = 280;
const M = { top: 12, right: 64, bottom: 26, left: 0 };

interface Props {
  width: number;
  rows: Row[];
  series: { id: string; label: string }[];
  currency: string;
  lines: boolean;
}

/** Stacked bars (or lines for one or two series) by month. Stacking offsets are pixel
 *  positions; every figure a person reads is the series' own string. */
function Chart({ width, rows, series, currency, lines }: Props) {
  const calm = useCalm();
  const [active, setActive] = useState<number | null>(null);
  const iw = Math.max(40, width - M.left - M.right);
  const ih = H - M.top - M.bottom;
  const x = scaleBand({ domain: rows.map((r) => r.x), range: [0, iw], padding: lines ? 0 : 0.36 });
  const centers = rows.map((r) => (x(r.x) ?? 0) + x.bandwidth() / 2);

  // Geometry: where each segment sits. Positives stack up from zero, negatives down.
  const stacks = rows.map((r) => {
    let up = 0;
    let down = 0;
    return series.map((s) => {
      const v = r.values[s.id];
      if (v === undefined) return null;
      if (lines) return { from: v, to: v };
      if (v >= 0) {
        const seg = { from: up, to: up + v };
        up += v;
        return seg;
      }
      const seg = { from: down, to: down + v };
      down += v;
      return seg;
    });
  });
  const ends = stacks.flatMap((st) => st.flatMap((seg) => (seg ? [seg.from, seg.to] : [])));
  const y = scaleLinear({ domain: [Math.min(0, ...ends), Math.max(0, ...ends)], range: [ih, 0], nice: 4 });
  const bw = Math.min(30, x.bandwidth());
  const step = labelStep(rows.length, iw);
  const focused = active ?? rows.length - 1;
  const row = active === null ? undefined : rows[active];

  return (
    <div style={{ position: "relative" }}>
      <svg
        width={width}
        height={H}
        role="img"
        aria-label="Spending by category and month. Use the left and right arrow keys to read each month."
        tabIndex={0}
        style={{ display: "block", overflow: "visible", touchAction: "pan-y" }}
        onKeyDown={(event) => {
          const next = stepFor(event.key, focused, rows.length);
          if (next !== null) {
            event.preventDefault();
            setActive(next);
          }
        }}
        onBlur={() => setActive(null)}
        onPointerMove={(event) => {
          const box = event.currentTarget.getBoundingClientRect();
          setActive(nearestIndex(centers, event.clientX - box.left - M.left));
        }}
        onPointerLeave={() => setActive(null)}
      >
        <g transform={`translate(${M.left},${M.top})`}>
          <GridY ticks={y.ticks(4)} y={y} width={iw} currency={currency} />
          {active !== null && (
            <line x1={centers[active]} x2={centers[active]} y1={0} y2={ih} stroke="var(--ink)" strokeOpacity={0.15} />
          )}
          {lines
            ? series.map((s, k) => {
                // A month with no spend is a gap in the line, not a zero.
                const pts = rows.map((r, i) => ({ px: centers[i] ?? 0, v: r.values[s.id] }));
                return (
                  <g key={s.id} data-series={s.id} data-kind="line">
                    <LinePath
                      data={pts}
                      x={(p) => p.px}
                      y={(p) => y(p.v ?? 0)}
                      defined={(p) => p.v !== undefined}
                      curve={curveMonotoneX}
                    >
                      {({ path }) => (
                        <motion.path
                          d={path(pts) ?? ""}
                          fill="none"
                          stroke={categoryColor(s.id)}
                          strokeWidth={2}
                          strokeLinecap="round"
                          initial={calm ? false : { pathLength: 0 }}
                          animate={{ pathLength: 1 }}
                          transition={{ duration: 0.6, ease: EASE_OUT, delay: calm ? 0 : k * 0.06 }}
                        />
                      )}
                    </LinePath>
                    {pts.map((p, i) =>
                      p.v === undefined || (active !== i && i !== rows.length - 1) ? null : (
                        <circle key={i} cx={p.px} cy={y(p.v)} r={4} fill={categoryColor(s.id)} stroke="var(--surface)" strokeWidth={2} />
                      ),
                    )}
                  </g>
                );
              })
            : rows.map((r, i) => {
                const bx = (x(r.x) ?? 0) + (x.bandwidth() - bw) / 2;
                const segs = stacks[i] ?? [];
                const dim = active !== null && active !== i;
                return (
                  <motion.g key={r.x} animate={{ opacity: dim ? 0.35 : 1 }} transition={{ duration: 0.16 }} data-kind="bar">
                    {series.map((s, k) => {
                      const seg = segs[k];
                      if (!seg) return null;
                      // 2px surface gap between stacked segments; only the top end is rounded.
                      const top = segs.slice(k + 1).every((n) => !n || Math.sign(n.to) !== Math.sign(seg.to));
                      const y0 = y(seg.from) - (seg.from === 0 ? 0 : seg.to >= 0 ? 1 : -1);
                      const y1 = y(seg.to) + (top ? 0 : seg.to >= 0 ? 1 : -1);
                      return (
                        <motion.path
                          key={s.id}
                          data-series={s.id}
                          initial={calm ? false : { d: barPath(bx, bw, y(0), y(0), top ? 4 : 0) }}
                          animate={{ d: barPath(bx, bw, y0, y1, top ? 4 : 0) }}
                          transition={{ ...SPRING, delay: calm ? 0 : i * 0.025 + k * 0.03 }}
                          fill={categoryColor(s.id)}
                        />
                      );
                    })}
                  </motion.g>
                );
              })}
          {rows.map((r, i) => {
            const show = i === focused || (i % step === 0 && Math.abs((centers[i] ?? 0) - (centers[focused] ?? 0)) > 40);
            return (
              <text
                key={r.x}
                x={centers[i]}
                y={ih + 18}
                textAnchor="middle"
                fontSize={11.5}
                fill={i === active ? "var(--ink)" : "var(--ink-3)"}
                fontWeight={i === active ? 600 : 400}
                aria-hidden="true"
              >
                {show ? monthTick(r.x, i === 0) : ""}
              </text>
            );
          })}
        </g>
      </svg>
      {row && active !== null && (
        <Tip x={centers[active] ?? 0} y={8} width={width}>
          <div style={{ fontWeight: 600, marginBottom: 6 }}>{formatMonth(row.x)}</div>
          {series.every((s) => row.strings[s.id] === undefined) ? (
            <div className="sub">No spending</div>
          ) : (
            [...series].reverse().map((s) =>
              row.strings[s.id] === undefined ? null : (
                <TipRow key={s.id} swatch={categoryColor(s.id)} label={s.label}>
                  <Money amount={row.strings[s.id] as string} currency={currency} />
                </TipRow>
              ),
            )
          )}
        </Tip>
      )}
    </div>
  );
}

export const SpendOverTimeRenderer: Renderer = ({ spec }) => {
  const currency = specCurrency(spec);
  const byMonth = new Map(pivotSeries(spec.series).map((r) => [r.x, r]));
  // A continuous month axis: a month with no spend is a gap, not a missing tick.
  const rows = (spec.period ? monthRange(spec.period.start, spec.period.end) : [...byMonth.keys()]).map(
    (x) => byMonth.get(x) ?? { x, values: {}, strings: {} },
  );
  const lines = spec.series.every((s) => s.kind === "line");
  const series = spec.series.map((s) => ({ id: s.id, label: s.label }));
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <ul className="legend" aria-label="Categories">
        {series.map((s) => (
          <li key={s.id}>
            <i className="key" style={{ background: categoryColor(s.id) }} aria-hidden="true" />
            {s.label}
          </li>
        ))}
      </ul>
      <Measure minHeight={H}>
        {(width) => <Chart width={width} rows={rows} series={series} currency={currency} lines={lines} />}
      </Measure>
    </div>
  );
};
