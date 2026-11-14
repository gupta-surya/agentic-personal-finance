import { motion } from "motion/react";
import { useState } from "react";
import { categoryColor } from "../lib/colors";
import { formatMoney, formatShare, signOf, toNumber } from "../lib/money";
import { EASE_OUT, useCalm } from "../ui/motion";
import { specCurrency } from "./chartData";
import type { Renderer } from "./registry";

interface Group {
  label: string;
  amount: string;
  share: string;
}

/** One proportion strip and a ranked list, linked on hover. Every amount and share is
 *  written out, so no group depends on its color. A group that netted below zero (more
 *  refunded than spent) is listed with its sign and left out of the strip, which can
 *  only show positive parts of a whole. */
export const SpendBreakdownRenderer: Renderer = ({ spec }) => {
  const calm = useCalm();
  const [hot, setHot] = useState<string | null>(null);
  const currency = specCurrency(spec);
  const amounts = spec.series.find((s) => s.id === "amount")?.points ?? [];
  const shares = new Map((spec.series.find((s) => s.id === "share")?.points ?? []).map((p) => [p.x, p.y ?? "0"]));
  const groups: Group[] = amounts.map((p) => ({ label: p.x, amount: p.y ?? "0", share: shares.get(p.x) ?? "0" }));
  const positive = groups.filter((g) => signOf(g.share) === "positive");
  const total = spec.assumptions.find((a) => a.key === "total");

  return (
    <div style={{ display: "grid", gap: 12 }}>
      {total && (
        <div style={{ display: "grid", gap: 2 }}>
          <span className="eyebrow">{total.label}</span>
          <span className="big">{total.value}</span>
        </div>
      )}
      <motion.div
        className="seg"
        aria-hidden="true"
        onPointerLeave={() => setHot(null)}
        initial={calm ? false : { clipPath: "inset(0 100% 0 0 round 3px)" }}
        animate={{ clipPath: "inset(0 0% 0 0 round 3px)" }}
        transition={{ duration: 0.6, ease: EASE_OUT }}
      >
        {positive.map((g) => (
          <i
            key={g.label}
            onPointerEnter={() => setHot(g.label)}
            style={{
              // Width from the catalog's share (geometry only).
              flex: `${toNumber(g.share)} 1 0`,
              background: categoryColor(g.label),
              opacity: hot && hot !== g.label ? 0.28 : 1,
            }}
          />
        ))}
      </motion.div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0 }} onPointerLeave={() => setHot(null)}>
        {groups.map((g, i) => {
          const negative = signOf(g.amount) === "negative";
          const dim = hot !== null && hot !== g.label;
          return (
            <motion.li
              key={g.label}
              className="bd-row"
              data-group={g.label}
              onPointerEnter={() => setHot(g.label)}
              initial={calm ? false : { opacity: 0, y: 4 }}
              animate={{ opacity: dim ? 0.45 : 1, y: 0 }}
              transition={{ opacity: { duration: 0.16 }, y: { duration: 0.3, ease: EASE_OUT, delay: calm ? 0 : 0.12 + i * 0.04 } }}
            >
              <i className="key" style={{ background: categoryColor(g.label) }} aria-hidden="true" />
              <span style={{ fontWeight: 500, minWidth: 0, overflowWrap: "anywhere" }}>{g.label}</span>
              <span className="money" data-sign={negative ? "negative" : undefined}>
                {negative && <span aria-hidden="true">▼ </span>}
                {formatMoney(g.amount, currency)}
                {negative && <span className="sr-only"> (negative: more refunded than spent)</span>}
              </span>
              <span className="sub" style={{ textAlign: "right" }}>
                {formatShare(g.share)}
              </span>
            </motion.li>
          );
        })}
      </ul>
    </div>
  );
};
