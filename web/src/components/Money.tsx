import NumberFlow from "@number-flow/react";
import { formatMoney, signOf, toNumber } from "../lib/money";
import { useCalm } from "../ui/motion";

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
      {showGlyph && <span className="glyph" aria-hidden="true">{GLYPH[sign]} </span>}
      {formatMoney(amount, currency)}
      {showGlyph && <span className="sr-only"> ({WORD[sign]})</span>}
    </span>
  );
}

/** A headline amount: the exact formatted string, with the cents stepped back. */
export function Figure({ amount, currency = "USD" }: { amount: string; currency?: string }) {
  const text = formatMoney(amount, currency);
  const dot = text.lastIndexOf(".");
  const negative = signOf(amount) === "negative";
  return (
    <span className="money" data-sign={negative ? "negative" : undefined}>
      {negative && <span className="glyph" aria-hidden="true">▼ </span>}
      {text.slice(0, dot)}
      <span className={negative ? undefined : "cents"}>{text.slice(dot)}</span>
      {negative && <span className="sr-only"> (negative)</span>}
    </span>
  );
}

// One locale for the guard and the animation, so the digits that roll are the digits the
// guard checked (NumberFlow would otherwise use the browser's locale).
const LOCALE = "en-US";
const INTL: Record<string, Intl.NumberFormat> = {};
const intl = (currency: string) =>
  (INTL[currency] ??= new Intl.NumberFormat(LOCALE, { style: "currency", currency }));

/** A headline amount that rolls its digits when it changes from one query result to
 *  another (never counting up from zero). NumberFlow needs a number, so it is used only
 *  when formatting that number reproduces the exact string; otherwise, for negatives,
 *  and under reduced motion, the exact string is shown as it is. */
export function FlowFigure({ amount, currency = "USD" }: { amount: string; currency?: string }) {
  const calm = useCalm();
  const exact = formatMoney(amount, currency);
  const value = toNumber(amount); // for the animation only; the text is checked below
  let roundTrips = false;
  try {
    roundTrips = intl(currency).format(value) === exact;
  } catch {
    roundTrips = false;
  }
  if (calm || signOf(amount) === "negative" || !roundTrips) {
    return <Figure amount={amount} currency={currency} />;
  }
  return (
    <span className="money" data-exact={exact}>
      <span className="sr-only">{exact}</span>
      <span aria-hidden="true">
        <NumberFlow
          value={value}
          locales={LOCALE}
          format={{ style: "currency", currency }}
          className="flow"
          transformTiming={{ duration: 320, easing: "cubic-bezier(0.23, 1, 0.32, 1)" }}
          spinTiming={{ duration: 320, easing: "cubic-bezier(0.23, 1, 0.32, 1)" }}
          opacityTiming={{ duration: 180, easing: "ease-out" }}
        />
      </span>
    </span>
  );
}
