import { useId, useState } from "react";
import type { ChartSpec } from "../api/types";
import { formatAsOf } from "../lib/time";
import { getRenderer } from "../renderers/registry";
import { ClarifyCard, type Choose } from "./ClarifyCard";
import { DataTable } from "./DataTable";

export type ChartState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; spec: ChartSpec };

const SOURCE_NAME: Record<string, string> = { question: "from the question", default: "default" };

/** The card around any ChartSpec: the finding as its title, the period beneath, the
 *  chart, then a quiet footer. Assumptions and sources sit in one "Details" disclosure
 *  (provenance stays one click away). The data table is always in the DOM, visually
 *  hidden until toggled, so screen readers get the exact figures either way. */
export function ChartFrame({
  state,
  onChoose,
  onRetry,
  compact = false,
  className = "",
}: {
  state: ChartState;
  onChoose?: Choose;
  onRetry?: () => void;
  /** A tile: shorter skeleton, no table toggle in the header. */
  compact?: boolean;
  className?: string;
}) {
  const tableId = useId();
  const headingId = useId();
  const [showTable, setShowTable] = useState(false);

  if (state.status === "loading") {
    return (
      <section className={`card ${className}`} aria-busy="true" aria-label="Loading chart">
        <div className="skeleton" style={{ height: 16, width: "45%" }} />
        <div className="skeleton" style={{ height: 12, width: "28%", marginTop: 8 }} />
        <div className="skeleton" style={{ height: compact ? 40 : 220, marginTop: 18 }} />
        <span className="sr-only" role="status">
          Loading chart
        </span>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className={`card ${className}`} role="alert">
        <h2 className="title">This chart could not be drawn</h2>
        <p className="sub" style={{ margin: "4px 0 12px" }}>
          {state.message}
        </p>
        {onRetry && (
          <button type="button" className="btn" onClick={onRetry}>
            Try again
          </button>
        )}
      </section>
    );
  }

  const { spec } = state;
  if (spec.clarify) return <ClarifyCard spec={spec} onChoose={onChoose} className={className} />;
  const resultIds = spec.sources.map((source) => source.result_id).join(", ");

  if (spec.table.rows.length === 0) {
    return (
      <section className={`card ${className}`} aria-labelledby={headingId}>
        <h2 className="title" id={headingId}>
          {spec.title}
        </h2>
        <p className="sub" style={{ margin: "2px 0 0" }}>
          {spec.period?.label}
        </p>
        <p className="sub" role="status" style={{ margin: "18px 0 4px", color: "var(--ink-2)" }}>
          No data for this period. Try a longer period.
        </p>
      </section>
    );
  }

  const Renderer = getRenderer(spec.template_id);
  const heading = Renderer?.heading?.(spec);

  return (
    <figure className={`card ${className}`} aria-labelledby={headingId}>
      <div className="cardhead">
        <div className="cardhead-text">
          <h2 className={heading ? "eyebrow" : "title"} id={headingId} style={{ margin: 0 }}>
            {heading ?? spec.title}
            {heading && <span className="sr-only">: {spec.title}</span>}
          </h2>
          <p className="sub" style={{ margin: 0 }}>
            {spec.period?.label}
          </p>
        </div>
        {Renderer && (
          <button
            type="button"
            className="btn-quiet"
            aria-pressed={showTable}
            aria-controls={tableId}
            onClick={() => setShowTable((value) => !value)}
          >
            {showTable ? "Hide table" : "Table"}
          </button>
        )}
      </div>

      <div style={{ marginTop: heading ? 6 : 16 }} title={`Source results: ${resultIds}`} data-result-ids={resultIds}>
        {Renderer ? (
          <div role="group" aria-label={`${spec.title} chart`}>
            <Renderer spec={spec} />
          </div>
        ) : (
          <p role="alert" className="sub">
            {`There is no chart for “${spec.template_id}” yet, so the data is shown as a table.`}
          </p>
        )}
      </div>

      <div className={showTable || !Renderer ? "" : "sr-only"} style={showTable || !Renderer ? { marginTop: 14, overflowX: "auto" } : undefined}>
        <DataTable spec={spec} id={tableId} />
      </div>

      <details className="details">
        <summary>Details</summary>
        {spec.assumptions.length > 0 && (
          <dl>
            {spec.assumptions.map((assumption) => (
              <div key={assumption.key} style={{ display: "contents" }}>
                <dt>{assumption.label}</dt>
                <dd>
                  {assumption.value} <span style={{ color: "var(--ink-3)" }}>({SOURCE_NAME[assumption.source] ?? assumption.source.replace("_", " ")})</span>
                </dd>
              </div>
            ))}
          </dl>
        )}
        <ul aria-label="Sources">
          {spec.sources.map((source) => (
            <li key={source.result_id}>
              {`${source.query} · ${source.result_id} · data ${source.data_version} · as of ${formatAsOf(source.as_of)}`}
            </li>
          ))}
        </ul>
      </details>
    </figure>
  );
}
