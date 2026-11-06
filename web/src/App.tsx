import { lazy, Suspense, useEffect, useState } from "react";
import { Explorer } from "./Explorer";

// The fixture page is development-only. `import.meta.env.DEV` is a build-time constant,
// so in production this is `null`, the dynamic import is removed, and src/dev is never
// bundled.
const Fixtures = import.meta.env.DEV ? lazy(() => import("./dev/Fixtures")) : null;

type Theme = "system" | "light" | "dark";

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
  const hash = useHash();
  const fixtures = Fixtures !== null && hash === "#/fixtures";
  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{fixtures ? "Chart fixtures" : "Charts"}</h1>
        <div className="flex items-center gap-4 text-sm">
          {Fixtures && (
            <a className="underline" href={fixtures ? "#/" : "#/fixtures"}>
              {fixtures ? "Live charts" : "Fixtures"}
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
        </div>
      </header>
      {fixtures && Fixtures ? (
        <Suspense fallback={null}>
          <Fixtures />
        </Suspense>
      ) : (
        <Explorer />
      )}
    </main>
  );
}
