// Per-viewer display preferences. Stored in this browser only (a convenience, never
// data): reads and writes are wrapped because storage can be blocked or throw.

export type Theme = "system" | "light" | "dark";
export const ACCENTS = [
  { id: "indigo", label: "Indigo", swatch: "#4f46e5" },
  { id: "forest", label: "Forest", swatch: "#15803d" },
  { id: "plum", label: "Plum", swatch: "#9d3fd6" },
  { id: "amber", label: "Amber", swatch: "#c2620a" },
  { id: "graphite", label: "Graphite", swatch: "#27272a" },
] as const;
export type Accent = (typeof ACCENTS)[number]["id"];

function read(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}
function write(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // storage unavailable: the choice lasts for this page view
  }
}

export function loadTheme(): Theme {
  const value = read("fa.theme");
  return value === "light" || value === "dark" ? value : "system";
}
export function loadAccent(): Accent {
  const value = read("fa.accent");
  return ACCENTS.some((a) => a.id === value) ? (value as Accent) : "indigo";
}

export function applyTheme(theme: Theme, persist = true): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  if (persist) write("fa.theme", theme);
}
export function applyAccent(accent: Accent, persist = true): void {
  if (accent === "indigo") document.documentElement.removeAttribute("data-accent");
  else document.documentElement.setAttribute("data-accent", accent);
  if (persist) write("fa.accent", accent);
}
