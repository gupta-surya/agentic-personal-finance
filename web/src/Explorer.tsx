import { useEffect, useMemo, useState } from "react";
import { renderChart } from "./api/client";
import { ChartFrame, type ChartState } from "./components/ChartFrame";
import { registerAllRenderers } from "./renderers";

registerAllRenderers();

interface Entry {
  key: string;
  label: string;
  templateId: string;
  /** Fixed params for this entry (the period and currency are added unless `fixed`). */
  params?: Record<string, unknown>;
  /** The entry takes its params as given: no period or currency controls. */
  fixed?: boolean;
}

const request = (templateId: string, preset: string) => ({
  label: "",
  template_id: templateId,
  params: { period: { preset } },
});

export const ENTRIES: Entry[] = [
  { key: "cash_flow", label: "Cash flow", templateId: "cash_flow" },
  { key: "spend_over_time", label: "Spending over time", templateId: "spend_over_time" },
  { key: "spend_breakdown", label: "Spending breakdown", templateId: "spend_breakdown" },
  { key: "kpi_spend", label: "Total spending", templateId: "kpi", params: { measure: "spend" } },
  { key: "kpi_income", label: "Total income", templateId: "kpi", params: { measure: "income" } },
  { key: "kpi_net", label: "Net cash flow", templateId: "kpi", params: { measure: "net" } },
  {
    key: "kpi_dining",
    label: "Dining spend",
    templateId: "kpi",
    params: { measure: "spend", category: "dining" },
  },
  {
    key: "clarify",
    label: "Not sure? (clarify demo)",
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
];

export const PERIODS = [
  ["this_month", "This month"],
  ["last_month", "Last month"],
  ["last_3_months", "Last 3 months"],
  ["last_6_months", "Last 6 months"],
  ["last_12_months", "Last 12 months"],
  ["year_to_date", "Year to date"],
  ["last_year", "Last year"],
] as const;

const select = "rounded border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-sm";

interface Request {
  templateId: string;
  params: Record<string, unknown>;
}

/** Pick a chart, period and currency; every change is one POST /charts/render and no
 *  model call. Choosing an option on a clarify card is the same call. */
export function Explorer() {
  const [entryKey, setEntryKey] = useState(ENTRIES[0]!.key);
  const [preset, setPreset] = useState("last_6_months");
  const [currency, setCurrency] = useState("USD");
  const [chosen, setChosen] = useState<Request | null>(null);
  const [state, setState] = useState<ChartState>({ status: "loading" });

  const entry = ENTRIES.find((e) => e.key === entryKey) ?? ENTRIES[0]!;
  const fromControls = useMemo<Request>(
    () => ({
      templateId: entry.templateId,
      params: entry.fixed ? (entry.params ?? {}) : { ...entry.params, period: { preset }, currency },
    }),
    [entry, preset, currency],
  );
  const active = chosen ?? fromControls;

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    renderChart(active.templateId, active.params, controller.signal)
      .then((spec) => setState({ status: "ready", spec }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, [active]);

  const change = (apply: () => void) => {
    setChosen(null); // touching a control takes over from a chosen option
    apply();
  };

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">
          Chart{" "}
          <select className={select} value={entryKey} onChange={(e) => change(() => setEntryKey(e.target.value))}>
            {ENTRIES.map((e) => (
              <option key={e.key} value={e.key}>
                {e.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Period{" "}
          <select
            className={select}
            value={preset}
            disabled={entry.fixed && !chosen}
            onChange={(e) => change(() => setPreset(e.target.value))}
          >
            {PERIODS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Currency{" "}
          <select
            className={select}
            value={currency}
            disabled={entry.fixed && !chosen}
            onChange={(e) => change(() => setCurrency(e.target.value))}
          >
            <option>USD</option>
            <option>EUR</option>
          </select>
        </label>
      </div>
      <ChartFrame
        state={state}
        onChoose={(templateId, params) => setChosen({ templateId, params })}
      />
    </>
  );
}
