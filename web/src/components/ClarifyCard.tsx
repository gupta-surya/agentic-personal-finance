import { useId } from "react";
import type { ChartSpec } from "../api/types";

export type Choose = (templateId: string, params: Record<string, unknown>) => void;

/** A question with options. Each option is a ready request for the render route, so
 *  choosing one never involves a model. */
export function ClarifyCard({ spec, onChoose }: { spec: ChartSpec; onChoose?: Choose }) {
  const headingId = useId();
  const clarify = spec.clarify;
  if (!clarify) return null;
  return (
    <section
      aria-labelledby={headingId}
      className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4"
    >
      <h2 id={headingId} className="text-base font-semibold">
        {clarify.question}
      </h2>
      <ul className="m-0 mt-3 flex list-none flex-wrap gap-2 p-0">
        {clarify.options.map((option) => (
          <li key={option.label}>
            <button
              type="button"
              disabled={!onChoose}
              onClick={() => onChoose?.(option.template_id, option.params)}
              className="rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1.5 text-sm hover:border-[var(--focus)] disabled:opacity-60"
            >
              {option.label}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
