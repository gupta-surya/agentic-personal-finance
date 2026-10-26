import { useId, useState } from "react";
import type { ChartSpec } from "../api/types";
import { getRenderer } from "../renderers/registry";
import { ClarifyCard, type Choose } from "./ClarifyCard";
import { DataTable } from "./DataTable";

export type ChartState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; spec: ChartSpec };

const card = "rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4";

/** Title, chart, assumptions, provenance and a table view around any ChartSpec.
 *  The table is always in the DOM (visually hidden until toggled) so screen readers
 *  get the data whether or not the chart can be read. */
export function ChartFrame({ state, onChoose }: { state: ChartState; onChoose?: Choose }) {
  const tableId = useId();
  const [showTable, setShowTable] = useState(false);

  if (state.status === "loading") {
    return (
      <section className={card} aria-busy="true" aria-label="Loading chart">
        <div className="h-5 w-1/3 animate-pulse rounded bg-[var(--surface-muted)]" />
        <div className="mt-4 h-48 animate-pulse rounded bg-[var(--surface-muted)]" />
        <span className="sr-only" role="status">
          Loading chart
        </span>
      </section>
    );
  }

  if (state.status === "error") {
    return (
      <section className={card} role="alert">
        <h2 className="text-base font-semibold">This chart could not be drawn</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">{state.message}</p>
      </section>
    );
  }

  const { spec } = state;
  if (spec.clarify) return <ClarifyCard spec={spec} onChoose={onChoose} />;
  const resultIds = spec.sources.map((source) => source.result_id).join(", ");

  if (spec.table.rows.length === 0) {
    return (
      <section className={card}>
        <h2 className="text-base font-semibold">{spec.title}</h2>
        <p className="mt-1 text-sm text-[var(--text-muted)]">{spec.period?.label}</p>
        <p className="mt-4 text-sm" role="status">
          No data for this period.
        </p>
      </section>
    );
  }

  const Renderer = getRenderer(spec.template_id);

  return (
    <figure className={`${card} m-0`}>
      <figcaption>
        <h2 className="text-base font-semibold">{spec.title}</h2>
        <p className="text-sm text-[var(--text-muted)]">{spec.period?.label}</p>
      </figcaption>

      <div className="mt-3" title={`Source results: ${resultIds}`} data-result-ids={resultIds}>
        {Renderer ? (
          <div role="group" aria-label={`${spec.title} chart`}>
            <Renderer spec={spec} />
          </div>
        ) : (
          <p role="alert" className="text-sm text-[var(--text-muted)]">
            {`There is no chart for “${spec.template_id}” yet, so the data is shown as a table.`}
          </p>
        )}
      </div>

      <div className="mt-3">
        {Renderer && (
          <button
            type="button"
            aria-pressed={showTable}
            aria-controls={tableId}
            onClick={() => setShowTable((value) => !value)}
            className="rounded border border-[var(--border)] px-2 py-1 text-sm"
          >
            {showTable ? "Hide data table" : "Show data table"}
          </button>
        )}
        <div className={showTable || !Renderer ? "mt-2 overflow-x-auto" : "sr-only"}>
          <DataTable spec={spec} id={tableId} />
        </div>
      </div>

      {spec.assumptions.length > 0 && (
        <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
          {spec.assumptions.map((assumption) => (
            <div key={assumption.key} className="contents">
              <dt className="text-[var(--text-muted)]">{assumption.label}</dt>
              <dd>
                {assumption.value}{" "}
                <span className="text-[var(--text-muted)]">
                  ({assumption.source.replace("_", " ")})
                </span>
              </dd>
            </div>
          ))}
        </dl>
      )}

      <details className="mt-3 text-sm">
        <summary className="cursor-pointer text-[var(--text-muted)]">Sources</summary>
        <ul className="mt-1 list-disc pl-5">
          {spec.sources.map((source) => (
            <li key={source.result_id}>
              {`${source.query} · ${source.result_id} · data ${source.data_version}`}
            </li>
          ))}
        </ul>
      </details>
    </figure>
  );
}
