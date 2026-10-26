import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Money } from "../components/Money";
import { formatMonth, formatMoney, signOf, toNumber } from "../lib/money";
import { axisMoney, pivotSeries, seriesLabel, type Row } from "./chartData";
import type { Renderer } from "./registry";

const COLORS = {
  inflow: "var(--chart-3)",
  outflow: "var(--chart-2)",
  net: "var(--chart-1)",
  running_net: "var(--chart-5)",
} as const;

function Tip({ active, payload, ids, labels }: TipProps) {
  const row = active ? payload?.[0]?.payload : undefined;
  if (!row) return null;
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm shadow">
      <strong>{formatMonth(row.x)}</strong>
      {ids.map((id) => {
        const amount = row.strings[id];
        return amount === undefined ? null : (
          <div key={id}>
            {labels[id]} <Money amount={amount} signed={id === "net" || id === "running_net"} />
          </div>
        );
      })}
    </div>
  );
}

interface TipProps {
  active?: boolean;
  payload?: { payload: Row }[];
  ids: string[];
  labels: Record<string, string>;
}

/** A net dot that is a triangle with the amount written out when the month is negative,
 *  so an overspent month never relies on color alone. */
function NetDot({ cx, cy, payload }: { cx?: number; cy?: number; payload?: Row }) {
  if (cx === undefined || cy === undefined || !payload) return <g />;
  const net = payload.strings.net;
  if (net === undefined || signOf(net) !== "negative") {
    return <circle cx={cx} cy={cy} r={3.5} fill="var(--chart-1)" />;
  }
  return (
    <g>
      <path d={`M ${cx - 6} ${cy - 5} L ${cx + 6} ${cy - 5} L ${cx} ${cy + 6} Z`} fill="var(--negative)" />
      <text x={cx} y={cy + 20} textAnchor="middle" fontSize={12} fill="var(--negative)">
        {formatMoney(net)}
      </text>
    </g>
  );
}

export const CashFlowRenderer: Renderer = ({ spec }) => {
  const rows = pivotSeries(spec.series);
  const ids = spec.series.map((s) => s.id);
  const labels = Object.fromEntries(ids.map((id) => [id, seriesLabel(spec, id)]));
  const data = rows.map((r) => ({ ...r, ...r.values }));
  const zero = spec.annotations.find((a) => a.kind === "reference_line" && a.y != null);

  return (
    <ResponsiveContainer width="100%" height={320}>
      <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="x" tickFormatter={formatMonth} tickLine={false} stroke="var(--text-muted)" />
        <YAxis tickFormatter={axisMoney} tickLine={false} axisLine={false} stroke="var(--text-muted)" width={56} />
        <Tooltip content={<Tip ids={ids} labels={labels} />} />
        <Legend />
        {zero?.y != null && <ReferenceLine y={toNumber(zero.y)} stroke="var(--text-muted)" />}
        <Bar dataKey="inflow" name={labels.inflow} fill={COLORS.inflow} radius={[3, 3, 0, 0]} />
        <Bar dataKey="outflow" name={labels.outflow} fill={COLORS.outflow} radius={[3, 3, 0, 0]} />
        <Line dataKey="net" name={labels.net} stroke={COLORS.net} strokeWidth={2} dot={<NetDot />} />
        {ids.includes("running_net") && (
          <Line
            dataKey="running_net"
            name={labels.running_net}
            stroke={COLORS.running_net}
            strokeWidth={2}
            strokeDasharray="5 4"
            dot={false}
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  );
};
