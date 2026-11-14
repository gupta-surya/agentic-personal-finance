import { FlowFigure, Money } from "../components/Money";
import { formatMoney, formatShare, signOf } from "../lib/money";
import { specCurrency } from "./chartData";
import type { Renderer } from "./registry";

/** The comparison's direction is written as a glyph and words, in a neutral color: a rise
 *  in spending is not "good" and a fall is not "bad", so the tile never judges. */
const DIRECTION = {
  positive: { glyph: "▲", word: "up", relation: "more than" },
  negative: { glyph: "▼", word: "down", relation: "less than" },
  zero: { glyph: "–", word: "unchanged", relation: "the same as" },
} as const;

export const KpiRenderer: Renderer = ({ spec }) => {
  const currency = specCurrency(spec);
  const point = (id: string) => spec.series.find((s) => s.id === id)?.points[0];
  const current = point("current")?.y;
  const previous = point("previous");
  const change = point("change")?.y;
  const percent = point("change_percent")?.y; // absent when the previous value was zero
  if (current == null) return null;
  const comparedWith = spec.assumptions.find((a) => a.key === "compared_with")?.value;
  // A net can go either way, so it always carries its glyph and sign; spend and income
  // are amounts, shown plainly (a negative one still gets its glyph).
  const signedMeasure = spec.params.measure === "net";

  const direction = change == null ? null : DIRECTION[signOf(change)];
  const signed = (text: string, amount: string) => (signOf(amount) === "positive" ? `+${text}` : text);

  return (
    <div style={{ display: "grid", gap: 12 }}>
      <div className="big" data-testid="kpi-value">
        {signedMeasure ? <Money amount={current} currency={currency} signed /> : <FlowFigure amount={current} currency={currency} />}
      </div>
      {change != null && direction ? (
        <div style={{ display: "grid", justifyItems: "start", gap: 6 }} data-testid="kpi-delta">
          <span className="chip">
            <span className="chip-glyph" aria-hidden="true">
              {direction.glyph}
            </span>
            <span className="sr-only">{direction.word}: </span>
            <span>{signed(formatMoney(change, currency), change)}</span>
            <span style={{ color: "var(--ink-3)" }}>{percent == null ? "n/a" : signed(formatShare(percent), percent)}</span>
          </span>
          <span className="sub">
            {direction.relation} the previous period
            {previous && (
              <>
                <br />
                {previous.x}
                {previous.y != null && (
                  <>
                    : <Money amount={previous.y} currency={currency} signed={signedMeasure} />
                  </>
                )}
              </>
            )}
          </span>
        </div>
      ) : (
        // History starts inside the previous period, or there is none: say so plainly.
        <p className="sub" style={{ margin: 0 }} data-testid="kpi-no-comparison">
          {comparedWith ?? "No comparison for this period"}
        </p>
      )}
    </div>
  );
};

/** The tile's heading: what is measured ("Spending", "Dining spending"). The finding
 *  sentence stays available to screen readers; the number is not repeated on screen. */
KpiRenderer.heading = (spec) => {
  const measure = spec.assumptions.find((a) => a.key === "measure")?.value ?? "Total";
  const category = spec.assumptions.find((a) => a.key === "category")?.value;
  return category ? `${category} ${measure.toLowerCase()}` : measure;
};
