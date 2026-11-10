import { lazy, Suspense, useEffect, useState } from "react";
import { Ask } from "./Ask";
import { type DataSource, fetchSource } from "./api/client";
import { Explorer } from "./Explorer";

// The fixture page is development-only. `import.meta.env.DEV` is a build-time constant,
// so in production this is `null`, the dynamic import is removed, and src/dev is never
// bundled.
const Fixtures = import.meta.env.DEV ? lazy(() => import("./dev/Fixtures")) : null;

type Theme = "system" | "light" | "dark";
type View = "ask" | "charts" | "fixtures";

const TITLES: Record<View, string> = { ask: "Ask", charts: "Charts", fixtures: "Chart fixtures" };

function applyTheme(theme: Theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

const useHash = () => {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
};

export function App() {
  const [theme, setTheme] = useState<Theme>("system");
  const [source, setSource] = useState<DataSource | null>(null);
  useEffect(() => {
    fetchSource().then(setSource, () => setSource(null)); // unknown: show no label
  }, []);
  const hash = useHash();
  const view: View =
    hash === "#/charts" ? "charts" : Fixtures !== null && hash === "#/fixtures" ? "fixtures" : "ask";

  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <header className="flex items-center justify-between">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-semibold">{TITLES[view]}</h1>
          {source && (
            <span className="text-sm text-[var(--text-muted)]" data-testid="data-source">
              {source === "postgres" ? "Your data" : "Synthetic data"}
            </span>
          )}
        </div>
        <nav className="flex items-center gap-4 text-sm">
          <a className="underline" href={view === "ask" ? "#/charts" : "#/"}>
            {view === "ask" ? "Charts" : "Ask"}
          </a>
          {Fixtures && (
            <a className="underline" href="#/fixtures">
              Fixtures
            </a>
          )}
          <label>
            Theme{" "}
            <select
              value={theme}
              onChange={(event) => {
                const next = event.target.value as Theme;
                setTheme(next);
                applyTheme(next);
              }}
              className="rounded border border-[var(--border)] bg-[var(--surface)] px-1 py-0.5"
            >
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </select>
          </label>
        </nav>
      </header>
      {view === "fixtures" && Fixtures ? (
        <Suspense fallback={null}>
          <Fixtures />
        </Suspense>
      ) : view === "charts" ? (
        <Explorer />
      ) : (
        <Ask />
      )}
    </main>
  );
}
