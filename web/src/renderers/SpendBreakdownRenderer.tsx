import { Bar, BarChart, Cell, LabelList, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Money } from "../components/Money";
import { formatMoney, formatShare, signOf, toNumber } from "../lib/money";
import { animationsOn, axisMoney, specCurrency } from "./chartData";
import type { Renderer } from "./registry";

interface Group {
  label: string;
  amount: string;
  share: string;
  value: number;
}

const DONUT_MAX_GROUPS = 6;
const colorAt = (i: number) => `var(--chart-${(i % 8) + 1})`;

export const SpendBreakdownRenderer: Renderer = ({ spec }) => {
  const currency = specCurrency(spec);
  const amounts = spec.series.find((s) => s.id === "amount")?.points ?? [];
  const shares = new Map((spec.series.find((s) => s.id === "share")?.points ?? []).map((p) => [p.x, p.y ?? "0"]));
  const groups: Group[] = amounts.map((p) => ({
    label: p.x,
    amount: p.y ?? "0",
    share: shares.get(p.x) ?? "0",
    value: toNumber(p.y ?? "0"),
  }));
  // A donut only reads well for a few positive slices; otherwise the bars carry it.
  const showDonut = groups.length <= DONUT_MAX_GROUPS && groups.every((g) => signOf(g.amount) === "positive");

  return (
    <div className="flex flex-wrap items-center gap-4">
      <div className="min-w-[320px] flex-1">
        <ResponsiveContainer width="100%" height={groups.length * 38 + 32}>
          <BarChart data={groups} layout="vertical" margin={{ top: 4, right: 150, bottom: 4, left: 0 }}>
            <XAxis
              type="number"
              tickFormatter={(value: number) => axisMoney(value, currency)}
              stroke="var(--text-muted)"
              tickLine={false}
              axisLine={false}
            />
            <YAxis type="category" dataKey="label" width={120} tickLine={false} axisLine={false} stroke="var(--text)" />
            <Tooltip
              cursor={{ fill: "var(--surface-muted)" }}
              content={({ active, payload }) => {
                const g = active ? (payload?.[0]?.payload as Group | undefined) : undefined;
                return g ? (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 py-2 text-sm shadow">
                    <strong>{g.label}</strong>
                    <div>
                      <Money amount={g.amount} currency={currency} /> · {formatShare(g.share)}
                    </div>
                  </div>
                ) : null;
              }}
            />
            <Bar isAnimationActive={animationsOn()} dataKey="value" radius={[0, 3, 3, 0]}>
              {groups.map((g, i) => (
                <Cell key={g.label} fill={signOf(g.amount) === "negative" ? "var(--negative)" : colorAt(i)} />
              ))}
              {/* The amount and share are written out, so no bar depends on its color. */}
              <LabelList
                dataKey="value"
                position="right"
                content={(props) => {
                  const { x, y, width, height, index } = props as unknown as {
                    x: number;
                    y: number;
                    width: number;
                    height: number;
                    index: number;
                  };
                  const g = groups[index];
                  if (!g) return null;
                  const negative = signOf(g.amount) === "negative";
                  return (
                    <text
                      x={(width >= 0 ? x + width : x) + 8}
                      y={y + height / 2}
                      dominantBaseline="middle"
                      fontSize={12}
                      fill={negative ? "var(--negative)" : "var(--text)"}
                    >
                      {`${negative ? "▼ " : ""}${formatMoney(g.amount, currency)} · ${formatShare(g.share)}`}
                    </text>
                  );
                }}
              />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
      {showDonut && (
        <div inert className="h-[180px] w-[180px]">
          {/* Decorative (the bars and table carry the data), so it must not take focus. */}
          <PieChart width={180} height={180} accessibilityLayer={false}>
            <Pie isAnimationActive={animationsOn()} data={groups} dataKey="value" nameKey="label" innerRadius={50} outerRadius={85} stroke="var(--surface)">
              {groups.map((g, i) => (
                <Cell key={g.label} fill={colorAt(i)} />
              ))}
            </Pie>
          </PieChart>
        </div>
      )}
    </div>
  );
};
