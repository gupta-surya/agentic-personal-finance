import { formatMoney, signOf } from "../lib/money";

const GLYPH = { positive: "▲", negative: "▼", zero: "" } as const;
const WORD = { positive: "positive", negative: "negative", zero: "" } as const;

/** An exact amount. Direction is shown by sign, glyph and screen-reader text, not by
 *  color alone. `signed` adds the glyph to positive amounts too (deltas, net). */
export function Money({
  amount,
  currency = "USD",
  signed = false,
}: {
  amount: string;
  currency?: string;
  signed?: boolean;
}) {
  const sign = signOf(amount);
  const showGlyph = sign === "negative" || (signed && sign === "positive");
  return (
    <span className="money" data-sign={sign}>
      {showGlyph && <span aria-hidden="true">{GLYPH[sign]} </span>}
      {formatMoney(amount, currency)}
      {showGlyph && <span className="sr-only"> ({WORD[sign]})</span>}
    </span>
  );
}
