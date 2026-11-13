import { useId } from "react";
import type { ChartSpec } from "../api/types";

export type Choose = (templateId: string, params: Record<string, unknown>) => void;

/** A question with options. Each option is a ready request for the render route, so
 *  choosing one never involves a model. */
export function ClarifyCard({ spec, onChoose, className = "" }: { spec: ChartSpec; onChoose?: Choose; className?: string }) {
  const headingId = useId();
  const clarify = spec.clarify;
  if (!clarify) return null;
  return (
    <section aria-labelledby={headingId} className={`card ${className}`}>
      <h2 id={headingId} className="title" style={{ fontSize: 18 }}>
        {clarify.question}
      </h2>
      <ul style={{ display: "flex", flexWrap: "wrap", gap: 8, listStyle: "none", margin: "14px 0 0", padding: 0 }}>
        {clarify.options.map((option) => (
          <li key={option.label}>
            <button
              type="button"
              disabled={!onChoose}
              onClick={() => onChoose?.(option.template_id, option.params)}
              className="btn"
              style={{ minHeight: 40, padding: "0 16px", color: "var(--ink)" }}
            >
              {option.label}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
