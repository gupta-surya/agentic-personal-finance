import type { Series } from "../api/types";
import { toNumber } from "../lib/money";
import type { Renderer } from "./registry";

const W = 120;
const H = 28;

/** A decorative line: the values it summarises are in the row's cells. Numbers are used
 *  only to place points. */
function Sparkline({ series }: { series: Series | undefined }) {
  const values = (series?.points ?? []).map((p) => toNumber(p.y ?? "0"));
  if (values.length < 2) return null;
  const lo = Math.min(...values);
  const span = Math.max(...values) - lo || 1; // a flat line sits mid-height
  const points = values
    .map((v, i) => `${(i / (values.length - 1)) * W},${H - 2 - ((v - lo) / span) * (H - 4)}`)
    .join(" ");
  return (
    <svg width={W} height={H} aria-hidden="true" focusable="false">
      <polyline points={points} fill="none" stroke="var(--chart-1)" strokeWidth={1.5} />
    </svg>
  );
}

/** The table is the chart: each row's figures and trend badge are the spec's own
 *  pre-formatted cells, with a sparkline from the matching series. */
export const CategoryTrendsRenderer: Renderer = ({ spec }) => {
  const { columns, rows } = spec.table;
  const trend = columns.length - 1; // the badge column, last
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c} scope="col" className="border-b border-[var(--border)] px-2 py-1 text-left font-medium">
                {c}
              </th>
            ))}
            <th scope="col" className="border-b border-[var(--border)] px-2 py-1 text-left font-medium">
              <span className="sr-only">Monthly spend</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]}>
              {row.map((cell, i) => (
                <td key={i} className={`px-2 py-1 ${i === trend ? "whitespace-nowrap font-medium" : ""}`}>
                  {cell}
                </td>
              ))}
              <td className="px-2 py-1">
                <Sparkline series={spec.series.find((s) => s.label === row[0])} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
