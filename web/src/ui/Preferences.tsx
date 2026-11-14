import { useState } from "react";
import { ACCENTS, type Accent, applyAccent, applyTheme, loadAccent, loadTheme, type Theme } from "../lib/prefs";

const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const THEME_NAME: Record<Theme, string> = { system: "Match system", light: "Light", dark: "Dark" };

function ThemeIcon({ theme }: { theme: Theme }) {
  if (theme === "light")
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <circle cx="8" cy="8" r="3" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  if (theme === "dark")
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
        <path d="M13.5 9.6A5.5 5.5 0 0 1 6.4 2.5a5.5 5.5 0 1 0 7.1 7.1Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
      </svg>
    );
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <rect x="2" y="3" width="12" height="8.5" rx="1.5" stroke="currentColor" strokeWidth="1.5" />
      <path d="M5.5 14h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

/** Accent and theme. The accent colors the data marks and the selection; categories keep
 *  their own colors whatever the accent. */
export function Preferences() {
  const [theme, setTheme] = useState<Theme>(loadTheme);
  const [accent, setAccent] = useState<Accent>(loadAccent);
  return (
    <div className="controls">
      <div className="swatches" role="radiogroup" aria-label="Accent color">
        {ACCENTS.map((a) => (
          <button
            key={a.id}
            type="button"
            role="radio"
            aria-checked={accent === a.id}
            aria-label={a.label}
            title={a.label}
            className="swatch"
            style={{ background: a.swatch }}
            onClick={() => {
              setAccent(a.id);
              applyAccent(a.id);
            }}
          />
        ))}
      </div>
      <button
        type="button"
        className="iconbtn"
        aria-label={`Theme: ${THEME_NAME[theme]}. Switch to ${THEME_NAME[NEXT[theme]]}`}
        title={`Theme: ${THEME_NAME[theme]}`}
        onClick={() => {
          const next = NEXT[theme];
          setTheme(next);
          applyTheme(next);
        }}
      >
        <ThemeIcon theme={theme} />
      </button>
    </div>
  );
}
