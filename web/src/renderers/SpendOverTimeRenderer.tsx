import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Money } from "../components/Money";
import { formatMonth } from "../lib/money";
import { animationsOn, axisMoney, monthRange, pivotSeries, specCurrency, type Row } from "./chartData";
import type { Renderer } from "./registry";

/** Uncategorized and the folded bucket are neutral; real categories take the palette. */
function colorFor(id: string, index: number): string {
  return id === "uncategorized" || id === "everything_else" ? "var(--chart-8)" : `var(--chart-${(index % 7) + 1})`;
}

interface TipProps {
  active?: boolean;
  payload?: { payload: Row }[];
  series: { id: string; label: string }[];
  currency: string;
}

function Tip({ active, payload, series, currency }: TipProps) {
  const row = active ? payload?.[0]?.payload : undefined;
  if (!row) return null;
  const shown = series.filter((s) => row.strings[s.id] !== undefined);
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm shadow">
      <strong>{formatMonth(row.x)}</strong>
      {shown.length === 0 ? (
        <div className="text-[var(--text-muted)]">No data</div>
      ) : (
        shown.map((s) => (
          <div key={s.id}>
            {s.label} <Money amount={row.strings[s.id] as string} currency={currency} />
          </div>
        ))
      )}
    </div>
  );
}

export const SpendOverTimeRenderer: Renderer = ({ spec }) => {
  const currency = specCurrency(spec);
  const byMonth = new Map(pivotSeries(spec.series).map((r) => [r.x, r]));
  // A continuous month axis: a month with no spend is a gap, not a missing tick.
  const data = monthRange(spec.period.start, spec.period.end).map((x) => {
    const row = byMonth.get(x) ?? { x, values: {}, strings: {} };
    return { ...row, ...row.values };
  });
  const asLines = spec.series.every((s) => s.kind === "line");
  const common = {
    data,
    margin: { top: 8, right: 16, bottom: 8, left: 0 },
  };
  const axes = [
    <CartesianGrid key="grid" vertical={false} stroke="var(--chart-grid)" />,
    <XAxis key="x" dataKey="x" tickFormatter={formatMonth} tickLine={false} stroke="var(--text-muted)" />,
    <YAxis
      key="y"
      tickFormatter={(value: number) => axisMoney(value, currency)}
      tickLine={false}
      axisLine={false}
      stroke="var(--text-muted)"
      width={72}
    />,
    <Tooltip key="tip" content={<Tip series={spec.series} currency={currency} />} />,
    <Legend key="legend" />,
  ];

  return (
    <ResponsiveContainer width="100%" height={320}>
      {asLines ? (
        <LineChart {...common}>
          {axes}
          {spec.series.map((s, i) => (
            <Line key={s.id} isAnimationActive={animationsOn()} dataKey={s.id} name={s.label} stroke={colorFor(s.id, i)} strokeWidth={2} connectNulls={false} />
          ))}
        </LineChart>
      ) : (
        <BarChart {...common}>
          {axes}
          {spec.series.map((s, i) => (
            <Bar key={s.id} isAnimationActive={animationsOn()} dataKey={s.id} name={s.label} stackId="spend" fill={colorFor(s.id, i)} />
          ))}
        </BarChart>
      )}
    </ResponsiveContainer>
  );
};
