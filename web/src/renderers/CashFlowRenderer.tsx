import { curveMonotoneX } from "@visx/curve";
import { scaleBand, scaleLinear, scalePoint } from "@visx/scale";
import { AreaClosed, LinePath } from "@visx/shape";
import { motion } from "motion/react";
import { useId, useState } from "react";
import { FlowFigure, Money } from "../components/Money";
import { formatMoney, formatMonth, signOf } from "../lib/money";
import { Measure } from "../ui/Measure";
import { EASE_OUT, SPRING, useCalm } from "../ui/motion";
import { pivotSeries, seriesLabel, specCurrency, type Row } from "./chartData";
import { barPath, GridY, labelStep, monthTick, nearestIndex, partialBar, stepFor } from "./primitives";
import type { Renderer } from "./registry";

const H = 260;
const M = { top: 10, right: 64, bottom: 26, left: 0 };
const IN = "var(--accent)";
const OUT = "var(--spend)";

/** Money in above the zero line, money out below it, the month's net as a dot. A month
 *  that went below zero has its net written out under the bar, with its sign. */
function MirrorBars({
  width,
  rows,
  currency,
  active,
  setActive,
  label,
}: {
  width: number;
  rows: Row[];
  currency: string;
  active: number | null;
  setActive: (i: number | null) => void;
  label: string;
}) {
  const calm = useCalm();
  const iw = Math.max(40, width - M.left - M.right);
  const ih = H - M.top - M.bottom;
  const x = scaleBand({ domain: rows.map((r) => r.x), range: [0, iw], padding: 0.42 });
  const values = rows.flatMap((r) => [r.values.inflow ?? 0, -(r.values.outflow ?? 0), r.values.net ?? 0]);
  const y = scaleLinear({ domain: [Math.min(0, ...values), Math.max(0, ...values)], range: [ih, 0], nice: 4 });
  const bw = Math.min(24, x.bandwidth());
  const step = labelStep(rows.length, iw);
  const centers = rows.map((r) => (x(r.x) ?? 0) + x.bandwidth() / 2);
  const focused = active ?? rows.length - 1;

  return (
    <svg
      width={width}
      height={H}
      role="img"
      aria-label={`${label}. Use the left and right arrow keys to read each month.`}
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
        {rows.map((r, i) => {
          const bx = (x(r.x) ?? 0) + (x.bandwidth() - bw) / 2;
          const inflow = r.values.inflow;
          const outflow = r.values.outflow;
          const net = r.strings.net;
          const below = net !== undefined && signOf(net) === "negative";
          const dim = active !== null && active !== i;
          const delay = calm ? 0 : i * 0.025;
          const show = i === focused || (i % step === 0 && Math.abs((centers[i] ?? 0) - (centers[focused] ?? 0)) > 40);
          return (
            <motion.g key={r.x} animate={{ opacity: dim ? 0.35 : 1 }} transition={{ duration: 0.16 }} data-month={r.x}>
              {inflow !== undefined && (
                <motion.path
                  data-series="inflow"
                  initial={calm ? false : { d: barPath(bx, bw, y(0), y(0)) }}
                  animate={{ d: barPath(bx, bw, y(0), y(inflow)) }}
                  transition={{ ...SPRING, delay }}
                  fill={IN}
                  {...partialBar(r.partial, IN)}
                />
              )}
              {outflow !== undefined && (
                <motion.path
                  data-series="outflow"
                  initial={calm ? false : { d: barPath(bx, bw, y(0) + 2, y(0) + 2) }}
                  animate={{ d: barPath(bx, bw, y(0) + 2, y(-outflow) + 2) }}
                  transition={{ ...SPRING, delay: delay + 0.04 }}
                  fill={OUT}
                  {...partialBar(r.partial, OUT)}
                />
              )}
              {r.values.net !== undefined && (
                <motion.g
                  initial={calm ? false : { opacity: 0 }}
                  animate={{ opacity: 1 }}
                  transition={{ delay: calm ? 0 : 0.45 + delay, duration: 0.2 }}
                >
                  {below ? (
                    // A downward triangle: the shape says "below zero" without color.
                    <path
                      d={`M${bx + bw / 2 - 6},${y(r.values.net) - 5} L${bx + bw / 2 + 6},${y(r.values.net) - 5} L${bx + bw / 2},${y(r.values.net) + 6} Z`}
                      fill="var(--negative)"
                      stroke="var(--surface)"
                      strokeWidth={2}
                    />
                  ) : (
                    <circle cx={bx + bw / 2} cy={y(r.values.net)} r={4.5} fill="var(--ink)" stroke="var(--surface)" strokeWidth={2.5} />
                  )}
                </motion.g>
              )}
              {below && net !== undefined && outflow !== undefined && (
                <text
                  x={bx + bw / 2}
                  y={Math.max(y(-outflow), y(r.values.net ?? 0)) + 18}
                  textAnchor="middle"
                  fontSize={11.5}
                  fontWeight={600}
                  fill="var(--negative)"
                >
                  {formatMoney(net, currency)}
                </text>
              )}
              <text
                x={bx + bw / 2}
                y={ih + 18}
                textAnchor="middle"
                fontSize={11.5}
                fill={i === active ? "var(--ink)" : "var(--ink-3)"}
                fontWeight={i === active ? 600 : 400}
              >
                {show ? monthTick(r.x, i === 0, r.partial) : ""}
              </text>
            </motion.g>
          );
        })}
      </g>
    </svg>
  );
}

/** The running net as a quiet area: how much the period added up to, month by month. */
function RunningNet({ width, rows, active, currency }: { width: number; rows: Row[]; active: number | null; currency: string }) {
  const calm = useCalm();
  const gradient = useId();
  const h = 96;
  const iw = Math.max(40, width - M.right);
  const x = scalePoint({ domain: rows.map((r) => r.x), range: [0, iw], padding: 0.3 });
  const values = rows.map((r) => r.values.running_net ?? 0);
  const y = scaleLinear({ domain: [Math.min(0, ...values), Math.max(0, ...values)], range: [h - 4, 6], nice: 3 });
  const pts = rows
    .filter((r) => r.values.running_net !== undefined)
    .map((r) => ({ px: x(r.x) ?? 0, py: y(r.values.running_net ?? 0) }));
  const dot = pts[active ?? pts.length - 1];
  return (
    <svg width={width} height={h} aria-hidden="true" style={{ display: "block", overflow: "visible" }}>
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.16} />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
        </linearGradient>
      </defs>
      <GridY ticks={y.ticks(2)} y={y} width={iw} currency={currency} />
      <AreaClosed data={pts} x={(p) => p.px} y={(p) => p.py} yScale={y} curve={curveMonotoneX} fill={`url(#${gradient})`} />
      <LinePath data={pts} x={(p) => p.px} y={(p) => p.py} curve={curveMonotoneX}>
        {({ path }) => (
          <motion.path
            data-series="running_net"
            d={path(pts) ?? ""}
            fill="none"
            stroke="var(--accent)"
            strokeWidth={2}
            strokeLinecap="round"
            initial={calm ? false : { pathLength: 0 }}
            animate={{ pathLength: 1 }}
            transition={{ duration: 0.6, ease: EASE_OUT }}
          />
        )}
      </LinePath>
      {dot && <circle cx={dot.px} cy={dot.py} r={4} fill="var(--accent)" stroke="var(--surface)" strokeWidth={2} />}
    </svg>
  );
}

function Stat({ label, swatch, amount, currency, signed }: { label: string; swatch?: string; amount?: string; currency: string; signed?: boolean }) {
  return (
    <div style={{ display: "grid", gap: 2 }}>
      <span className="eyebrow" style={{ display: "flex", alignItems: "center", gap: 7 }}>
        {swatch && <i className="key" style={{ background: swatch }} aria-hidden="true" />}
        {label}
      </span>
      <span className="stat-value">
        {amount === undefined ? (
          <span className="sub">No data</span>
        ) : signed ? (
          // A net is signed both ways: glyph, sign and words, never color alone.
          <Money amount={amount} currency={currency} signed />
        ) : (
          <FlowFigure amount={amount} currency={currency} />
        )}
      </span>
    </div>
  );
}

export const CashFlowRenderer: Renderer = ({ spec }) => {
  const [active, setActive] = useState<number | null>(null);
  const rows = pivotSeries(spec.series);
  const currency = specCurrency(spec);
  if (rows.length === 0) return null;
  const month = rows[active ?? rows.length - 1] ?? rows[rows.length - 1]!;
  const hasRunning = spec.series.some((s) => s.id === "running_net");

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div>
        <p className="sub" style={{ margin: "0 0 8px" }} aria-live="polite">
          {formatMonth(month.x)}
        </p>
        <div className="stats">
          <Stat label={seriesLabel(spec, "inflow")} swatch={IN} amount={month.strings.inflow} currency={currency} />
          <Stat label={seriesLabel(spec, "outflow")} swatch={OUT} amount={month.strings.outflow} currency={currency} />
          <Stat label={seriesLabel(spec, "net")} swatch="var(--ink)" amount={month.strings.net} currency={currency} signed />
        </div>
      </div>
      <Measure minHeight={H}>
        {(width) => (
          <MirrorBars
            width={width}
            rows={rows}
            currency={currency}
            active={active}
            setActive={setActive}
            label={`${seriesLabel(spec, "inflow")} above zero and ${seriesLabel(spec, "outflow").toLowerCase()} below, by month; the dot is the month's ${seriesLabel(spec, "net").toLowerCase()}`}
          />
        )}
      </Measure>
      {hasRunning && (
        <div style={{ borderTop: "1px solid var(--line)", paddingTop: 12, display: "grid", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap", alignItems: "baseline" }}>
            <span className="eyebrow">
              {seriesLabel(spec, "running_net")} through {formatMonth(month.x)}
            </span>
            {month.strings.running_net !== undefined && (
              <span style={{ fontWeight: 600 }}>
                <Money amount={month.strings.running_net} currency={currency} signed />
              </span>
            )}
          </div>
          <Measure minHeight={96}>
            {(width) => <RunningNet width={width} rows={rows} active={active} currency={currency} />}
          </Measure>
        </div>
      )}
    </div>
  );
};
