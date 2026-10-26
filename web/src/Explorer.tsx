import { useEffect, useState } from "react";
import { renderChart } from "./api/client";
import { ChartFrame, type ChartState } from "./components/ChartFrame";
import { registerAllRenderers } from "./renderers";

registerAllRenderers();

export const TEMPLATES = [{ id: "cash_flow", label: "Cash flow" }] as const;

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

/** Pick a template, period and currency; every change is one POST /charts/render and no
 *  model call. This is the same path sliders and suggestion chips will use. */
export function Explorer() {
  const [templateId, setTemplateId] = useState<string>(TEMPLATES[0].id);
  const [preset, setPreset] = useState<string>("last_6_months");
  const [currency, setCurrency] = useState("USD");
  const [state, setState] = useState<ChartState>({ status: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    setState({ status: "loading" });
    renderChart(templateId, { period: { preset }, currency }, controller.signal)
      .then((spec) => setState({ status: "ready", spec }))
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
      });
    return () => controller.abort();
  }, [templateId, preset, currency]);

  return (
    <>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">
          Chart{" "}
          <select className={select} value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            {TEMPLATES.map((t) => (
              <option key={t.id} value={t.id}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Period{" "}
          <select className={select} value={preset} onChange={(e) => setPreset(e.target.value)}>
            {PERIODS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Currency{" "}
          <select className={select} value={currency} onChange={(e) => setCurrency(e.target.value)}>
            <option>USD</option>
            <option>EUR</option>
          </select>
        </label>
      </div>
      <ChartFrame state={state} />
    </>
  );
}
