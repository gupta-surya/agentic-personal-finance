import { formatMoney, formatShare, signOf } from "../lib/money";
import { specCurrency } from "./chartData";
import type { Renderer } from "./registry";

/** The comparison's direction is written as a glyph and words, in a neutral color: a rise
 *  in spending is not "good" and a fall is not "bad", so the tile never judges. */
const DIRECTION = {
  positive: { glyph: "▲", word: "up" },
  negative: { glyph: "▼", word: "down" },
  zero: { glyph: "", word: "unchanged" },
} as const;

export const KpiRenderer: Renderer = ({ spec }) => {
  const currency = specCurrency(spec);
  const point = (id: string) => spec.series.find((s) => s.id === id)?.points[0];
  const current = point("current")?.y;
  const previous = point("previous");
  const change = point("change")?.y;
  const percent = point("change_percent")?.y; // absent when the previous value was zero
  if (current == null) return null;

  const direction = change == null ? null : DIRECTION[signOf(change)];
  const signed = (text: string, amount: string) => (signOf(amount) === "positive" ? `+${text}` : text);

  return (
    <div className="space-y-2">
      <div className="text-4xl font-semibold tracking-tight" data-testid="kpi-value">
        {formatMoney(current, currency)}
      </div>
      {change != null && direction && (
        <p className="text-sm text-[var(--text-muted)]" data-testid="kpi-delta">
          {direction.glyph && <span aria-hidden="true">{direction.glyph} </span>}
          <span className="sr-only">{direction.word}: </span>
          {signed(formatMoney(change, currency), change)}
          {" ("}
          {percent == null ? "n/a" : signed(formatShare(percent), percent)}
          {") vs "}
          {previous?.x}
        </p>
      )}
      {previous?.y != null && (
        <p className="text-sm text-[var(--text-muted)]">
          Previous period: {formatMoney(previous.y, currency)}
        </p>
      )}
    </div>
  );
};
