import { useCallback, useEffect, useState } from "react";
import { renderChart } from "./api/client";
import { ChartFrame, type ChartState } from "./components/ChartFrame";
import { registerAllRenderers } from "./renderers";

registerAllRenderers();

export interface CardDef {
  key: string;
  templateId: string;
  /** Fixed params; the period and currency controls are added unless `fixed`. */
  params?: Record<string, unknown>;
  /** The card takes its params as given (its own window, like category trends). */
  fixed?: boolean;
}

export interface Section {
  layout: "grid-2" | "grid-3" | "stack";
  cards: CardDef[];
}

export interface Page {
  id: string;
  label: string;
  sections: Section[];
  dev?: boolean;
}

const kpi = (key: string, params: Record<string, unknown>): CardDef => ({ key, templateId: "kpi", params });
const request = (templateId: string, preset: string) => ({ label: "", template_id: templateId, params: { period: { preset } } });

export const PAGES: Page[] = [
  {
    id: "overview",
    label: "Overview",
    sections: [
      {
        layout: "grid-3",
        cards: [kpi("kpi_spend", { measure: "spend" }), kpi("kpi_income", { measure: "income" }), kpi("kpi_net", { measure: "net" })],
      },
      { layout: "stack", cards: [{ key: "cash_flow", templateId: "cash_flow" }] },
      {
        layout: "grid-2",
        cards: [
          { key: "spend_breakdown", templateId: "spend_breakdown" },
          { key: "category_trends", templateId: "category_trends", fixed: true, params: { months: 6 } },
        ],
      },
    ],
  },
  {
    id: "spending",
    label: "Spending",
    sections: [
      { layout: "grid-2", cards: [kpi("kpi_spend", { measure: "spend" }), kpi("kpi_dining", { measure: "spend", category: "dining" })] },
      { layout: "stack", cards: [{ key: "spend_over_time", templateId: "spend_over_time" }] },
      {
        layout: "grid-2",
        cards: [
          { key: "spend_breakdown", templateId: "spend_breakdown" },
          { key: "category_trends", templateId: "category_trends", fixed: true, params: { months: 6 } },
        ],
      },
    ],
  },
  {
    id: "cash-flow",
    label: "Cash flow",
    sections: [
      { layout: "grid-2", cards: [kpi("kpi_income", { measure: "income" }), kpi("kpi_net", { measure: "net" })] },
      { layout: "stack", cards: [{ key: "cash_flow", templateId: "cash_flow" }] },
    ],
  },
  {
    id: "clarify",
    label: "Clarify demo",
    dev: true,
    sections: [
      {
        layout: "stack",
        cards: [
          {
            key: "clarify",
            templateId: "clarify",
            fixed: true,
            params: {
              question: "Which view of your spending do you want?",
              options: [
                { ...request("spend_breakdown", "last_6_months"), label: "Where it went, last 6 months" },
                { ...request("spend_over_time", "last_6_months"), label: "How it changed, last 6 months" },
                { ...request("cash_flow", "last_6_months"), label: "Am I spending more than I earn?" },
              ],
            },
          },
        ],
      },
    ],
  },
];

export const PERIODS = [
  { id: "this_month", label: "1M", name: "This month" },
  { id: "last_3_months", label: "3M", name: "Last 3 months" },
  { id: "last_6_months", label: "6M", name: "Last 6 months" },
  { id: "last_12_months", label: "12M", name: "Last 12 months" },
  { id: "year_to_date", label: "YTD", name: "Year to date" },
  { id: "all_time", label: "All", name: "All time" },
] as const;
export const MORE_PERIODS = [
  { id: "last_month", name: "Last month" },
  { id: "last_year", name: "Last year" },
] as const;

interface Request {
  templateId: string;
  params: Record<string, unknown>;
}

/** One card: one POST /charts/render per change of its inputs, and no model call.
 *  Choosing an option on a clarify card is the same call. */
export function ChartCard({ def, preset, currency }: { def: CardDef; preset: string; currency: string }) {
  const [chosen, setChosen] = useState<Request | null>(null);
  const [state, setState] = useState<ChartState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const fromControls: Request = {
    templateId: def.templateId,
    params: def.fixed ? (def.params ?? {}) : { ...def.params, period: { preset }, currency },
  };
  const active = chosen ?? fromControls;
  const key = JSON.stringify(active);

  useEffect(() => {
    const controller = new AbortController();
    const { templateId, params } = JSON.parse(key) as Request;
    // Keep the last chart on screen while the next one loads, so a period change morphs
    // instead of flashing a skeleton; the first load shows the skeleton.
    setState((previous) => (previous.status === "ready" && previous.spec.template_id === templateId ? previous : { status: "loading" }));
    renderChart(templateId, params, controller.signal)
      .then((spec) => setState({ status: "ready", spec }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, [key, attempt]);

  // A control change takes over from a chosen clarify option.
  useEffect(() => setChosen(null), [preset, currency]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return (
    <ChartFrame
      state={state}
      compact={def.templateId === "kpi"}
      onRetry={retry}
      onChoose={(templateId, params) => setChosen({ templateId, params })}
    />
  );
}

export function PageView({ page, preset, currency }: { page: Page; preset: string; currency: string }) {
  return (
    <div className="stack">
      {page.sections.map((section, i) => (
        <div key={i} className={section.layout}>
          {section.cards.map((def) => (
            <ChartCard key={def.key} def={def} preset={preset} currency={currency} />
          ))}
        </div>
      ))}
    </div>
  );
}
