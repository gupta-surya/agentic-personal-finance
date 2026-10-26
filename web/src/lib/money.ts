// Money arrives as exact decimal strings ("-210.75"). The browser never does arithmetic
// on it: labels and tooltips are formatted from the string, and toNumber exists only to
// place marks on a chart.

const DECIMAL = /^(-?)(\d+)(?:\.(\d+))?$/;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const SYMBOLS: Record<string, string> = { USD: "$", EUR: "€", GBP: "£" };

export type Sign = "positive" | "negative" | "zero";

function parse(amount: string): { negative: boolean; whole: string; fraction: string } {
  const match = DECIMAL.exec(amount);
  if (!match) throw new Error(`not a decimal string: ${JSON.stringify(amount)}`);
  return { negative: match[1] === "-", whole: match[2] ?? "0", fraction: match[3] ?? "" };
}

/** For chart geometry only. Never format or sum the result. */
export function toNumber(amount: string): number {
  parse(amount);
  return Number(amount);
}

export function signOf(amount: string): Sign {
  const { negative, whole, fraction } = parse(amount);
  if (/^0*$/.test(whole + fraction)) return "zero";
  return negative ? "negative" : "positive";
}

/** "-210.75" -> "−$210.75". Digits are kept exactly as received; only grouping is added. */
export function formatMoney(amount: string, currency = "USD"): string {
  const { negative, whole, fraction } = parse(amount);
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const symbol = SYMBOLS[currency] ?? `${currency} `;
  const sign = negative && signOf(amount) !== "zero" ? "−" : "";
  return `${sign}${symbol}${grouped}.${fraction.padEnd(2, "0")}`;
}

/** "2026-03-01" -> "Mar 2026". */
export function formatMonth(isoDate: string): string {
  const match = /^(\d{4})-(\d{2})/.exec(isoDate);
  const month = match ? MONTHS[Number(match[2]) - 1] : undefined;
  if (!match || !month) throw new Error(`not an ISO date: ${JSON.stringify(isoDate)}`);
  return `${month} ${match[1]}`;
}

/** A fraction string from the API ("0.1234") -> "12.34%", by moving the decimal point. */
export function formatShare(fraction: string): string {
  const { negative, whole, fraction: digits } = parse(fraction);
  const padded = digits.padEnd(2, "0");
  const percentWhole = `${whole}${padded.slice(0, 2)}`.replace(/^0+(?=\d)/, "");
  const rest = padded.slice(2).replace(/0+$/, "");
  return `${negative ? "−" : ""}${percentWhole}${rest ? `.${rest}` : ""}%`;
}
