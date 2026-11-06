/** "2026-04-02T12:00:00Z" -> "2026-04-02 12:00 UTC" (any offset is converted to UTC). */
export function formatAsOf(iso: string): string {
  const time = new Date(iso);
  if (Number.isNaN(time.getTime())) return iso;
  return `${time.toISOString().slice(0, 16).replace("T", " ")} UTC`;
}
