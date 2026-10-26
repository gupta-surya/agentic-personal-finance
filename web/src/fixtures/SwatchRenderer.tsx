import { Money } from "../components/Money";
import { formatMonth, toNumber } from "../lib/money";
import type { Renderer } from "../renderers/registry";

/** Dev-only stand-in for a real chart: one bar per point, colored from the chart tokens,
 *  so the fixture page shows the palette and the money cues in both themes. The real
 *  renderers arrive with the templates, once the chart library is chosen (spec 05). */
export const SwatchRenderer: Renderer = ({ spec }) => {
  const max = Math.max(...spec.series.flatMap((s) => s.points.map((p) => Math.abs(toNumber(p.y ?? "0")))));
  return (
    <ul className="m-0 list-none space-y-2 p-0">
      {spec.series.map((series, index) => (
        <li key={series.id}>
          <div className="text-sm font-medium">{series.label}</div>
          {series.points.map((point) => (
            <div key={point.x} className="flex items-center gap-2 text-sm">
              <span className="w-20 text-[var(--text-muted)]">{formatMonth(point.x)}</span>
              <span
                aria-hidden="true"
                className="inline-block h-3 rounded-sm"
                style={{
                  width: `${(Math.abs(toNumber(point.y ?? "0")) / max) * 60}%`,
                  background: `var(--chart-${(index % 8) + 1})`,
                }}
              />
              <Money amount={point.y ?? "0"} signed={series.id === "net"} />
            </div>
          ))}
        </li>
      ))}
    </ul>
  );
};
