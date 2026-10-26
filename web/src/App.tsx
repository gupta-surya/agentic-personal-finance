import { useEffect, useState } from "react";
import { ChartFrame } from "./components/ChartFrame";
import { Explorer } from "./Explorer";
import { emptySpec, swatchSpec, unknownTemplateSpec } from "./fixtures/specs";
import { SwatchRenderer } from "./fixtures/SwatchRenderer";
import { getRenderer, registerRenderer } from "./renderers/registry";

type Theme = "system" | "light" | "dark";

function applyTheme(theme: Theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

/** Frame states from canned specs: no API needed. Open with #/fixtures. */
function Fixtures() {
  if (!getRenderer("fixture_swatch")) registerRenderer("fixture_swatch", SwatchRenderer);
  return (
    <>
      <ChartFrame state={{ status: "ready", spec: swatchSpec }} />
      <ChartFrame state={{ status: "ready", spec: unknownTemplateSpec }} />
      <ChartFrame state={{ status: "ready", spec: emptySpec }} />
      <ChartFrame state={{ status: "loading" }} />
      <ChartFrame state={{ status: "error", message: "The render request failed (HTTP 422)." }} />
    </>
  );
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
  const fixtures = useHash() === "#/fixtures";
  return (
    <main className="mx-auto max-w-3xl space-y-4 px-4 py-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">{fixtures ? "Chart fixtures" : "Charts"}</h1>
        <div className="flex items-center gap-4 text-sm">
          <a className="underline" href={fixtures ? "#/" : "#/fixtures"}>
            {fixtures ? "Live charts" : "Fixtures"}
          </a>
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
      {fixtures ? <Fixtures /> : <Explorer />}
    </main>
  );
}
