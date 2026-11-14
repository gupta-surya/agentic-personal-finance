// Category identity colors. A category keeps its color everywhere in the app and in
// every period, whatever its rank: the color follows the entity, not its position.
// Seven validated hues for sixteen default categories, so two rare categories can share
// a hue; the common ones are spread out, and every mark is also labelled in words.

const SLOT: Record<string, number> = {
  rent: 1,
  travel: 2,
  groceries: 3,
  dining: 4,
  transport: 5,
  utilities: 6,
  shopping: 7,
  health: 6,
  subscriptions: 2,
  entertainment: 7,
  education: 5,
  gifts_donations: 3,
  fees_interest: 4,
  savings_investments: 1,
  other: 5,
};

const NEUTRAL = new Set(["uncategorized", "everything_else"]);

/** "category:fees_interest", "Fees interest" or "everything_else" -> a stable key. */
export function categoryKey(idOrLabel: string): string {
  return idOrLabel.replace(/^category:/, "").trim().toLowerCase().replace(/\s+/g, "_");
}

function hashSlot(key: string): number {
  let h = 0;
  for (const ch of key) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return (h % 7) + 1;
}

/** CSS color for a category series id or label. */
export function categoryColor(idOrLabel: string): string {
  const key = categoryKey(idOrLabel);
  if (NEUTRAL.has(key)) return "var(--series-neutral)";
  return `var(--series-${SLOT[key] ?? hashSlot(key)})`;
}
