import { lazy, type ReactNode, Suspense, useEffect, useState } from "react";
import { type DataSource, fetchSource } from "./api/client";
import { MORE_PERIODS, PAGES, PageView, PERIODS } from "./pages";
import { Preferences } from "./ui/Preferences";
import { Segmented } from "./ui/Segmented";

// The fixture page is development-only. `import.meta.env.DEV` is a build-time constant,
// so in production this is `null`, the dynamic import is removed, and src/dev is never
// bundled.
const Fixtures = import.meta.env.DEV ? lazy(() => import("./dev/Fixtures")) : null;

const useHash = () => {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => setHash(window.location.hash);
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
};

const ICONS: Record<string, ReactNode> = {
  overview: <path d="M2.5 2.5h4.5v5H2.5zM9 2.5h4.5v3H9zM9 7.5h4.5v6H9zM2.5 9.5h4.5v4H2.5z" />,
  spending: <path d="M3 13.5V8M8 13.5V3M13 13.5V6" />,
  "cash-flow": <path d="M2.5 10.5l3.5-3.5 3 3 4.5-5M10 5h3.5v3.5" />,
  clarify: <path d="M6 6a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6.9V10M8 12.5v.5" />,
  fixtures: <path d="M3 3h10v10H3zM3 8h10M8 3v10" />,
};

function NavIcon({ id }: { id: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[id]}
    </svg>
  );
}

export function App() {
  const [source, setSource] = useState<DataSource | null>(null);
  const [preset, setPreset] = useState("last_6_months");
  const [currency, setCurrency] = useState("USD");
  useEffect(() => {
    fetchSource().then(setSource, () => setSource(null)); // unknown: show no label
  }, []);
  const hash = useHash();

  const pages = PAGES.filter((p) => !p.dev || import.meta.env.DEV);
  const fixtures = Fixtures !== null && hash === "#/fixtures";
  const page = pages.find((p) => hash === `#/${p.id}`) ?? pages[0]!;
  const current = fixtures ? "fixtures" : page.id;
  const usesControls = !fixtures && page.sections.some((s) => s.cards.some((c) => !c.fixed));
  const nav = [
    ...pages.map((p) => ({ id: p.id, label: p.label, href: p.id === "overview" ? "#/" : `#/${p.id}` })),
    ...(Fixtures ? [{ id: "fixtures", label: "Fixtures", href: "#/fixtures" }] : []),
  ];
  const links = nav.map((n) => (
    <a key={n.id} className="nav" href={n.href} aria-current={n.id === current ? "page" : undefined}>
      <NavIcon id={n.id} />
      {n.label}
    </a>
  ));
  const sourceBadge = source && (
    <span className="badge" data-testid="data-source">
      {source === "postgres" ? "Your data" : "Synthetic data"}
    </span>
  );

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <i className="brand-mark" aria-hidden="true" />
          Finance
        </div>
        <nav aria-label="Main">{links}</nav>
        <div className="side-foot">
          {sourceBadge}
          <span className="privacy">
            <i className="privacy-dot" aria-hidden="true" />
            Running on this device
          </span>
        </div>
      </aside>
      <div style={{ minWidth: 0 }}>
        <nav className="mobile-nav" aria-label="Main, compact">
          {links}
        </nav>
        <main className="content">
          <header className="pagehead">
            <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
              <h1>{fixtures ? "Chart fixtures" : page.label}</h1>
            </div>
            <Preferences />
          </header>
          {usesControls && (
            <div className="controls" style={{ marginBottom: 18 }}>
              <Segmented
                label="Period"
                items={PERIODS}
                value={(PERIODS.some((p) => p.id === preset) ? preset : "") as (typeof PERIODS)[number]["id"]}
                onChange={setPreset}
              />
              <label className="sub" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="sr-only">Other periods</span>
                <select className="select" value={MORE_PERIODS.some((p) => p.id === preset) ? preset : ""} onChange={(e) => e.target.value && setPreset(e.target.value)}>
                  <option value="">More periods</option>
                  {MORE_PERIODS.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </label>
              <label className="sub" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span className="sr-only">Currency</span>
                <select className="select" value={currency} onChange={(e) => setCurrency(e.target.value)} aria-label="Currency">
                  <option>USD</option>
                  <option>EUR</option>
                </select>
              </label>
            </div>
          )}
          {fixtures && Fixtures ? (
            <Suspense fallback={null}>
              <div className="stack">
                <Fixtures />
              </div>
            </Suspense>
          ) : (
            <PageView key={page.id} page={page} preset={preset} currency={currency} />
          )}
        </main>
      </div>
    </div>
  );
}
