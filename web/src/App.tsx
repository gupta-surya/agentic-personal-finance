import { useState } from "react";
import { ChartFrame } from "./components/ChartFrame";
import { emptySpec, swatchSpec, unknownTemplateSpec } from "./fixtures/specs";
import { SwatchRenderer } from "./fixtures/SwatchRenderer";
import { getRenderer, registerRenderer } from "./renderers/registry";

if (!getRenderer("fixture_swatch")) registerRenderer("fixture_swatch", SwatchRenderer);

type Theme = "system" | "light" | "dark";

function applyTheme(theme: Theme) {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
}

/** Dev fixture page: every frame state, from canned specs, with a theme switch. */
export function App() {
  const [theme, setTheme] = useState<Theme>("system");
  return (
    <main className="mx-auto max-w-3xl space-y-6 px-4 py-6">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">Chart fixtures</h1>
        <label className="text-sm">
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
      </header>
      <ChartFrame state={{ status: "ready", spec: swatchSpec }} />
      <ChartFrame state={{ status: "ready", spec: unknownTemplateSpec }} />
      <ChartFrame state={{ status: "ready", spec: emptySpec }} />
      <ChartFrame state={{ status: "loading" }} />
      <ChartFrame state={{ status: "error", message: "The render request failed (HTTP 422)." }} />
    </main>
  );
}
