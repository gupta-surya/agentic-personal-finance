import type { ChartSpec } from "../api/types";

// Canned specs shaped like the API's output (money as strings). Values mirror the
// cash_flow contract example. They exist to exercise the frame, tokens and registry.

const source = {
  result_id: "res_7f3b",
  query: "cash_flow",
  data_version: "dv_12",
  as_of: "2026-04-02T12:00:00Z",
};

export const swatchSpec: ChartSpec = {
  template_id: "fixture_swatch",
  title: "Cash flow, Feb–Mar 2026",
  params: { period: { preset: "custom" } },
  period: { preset: "custom", start: "2026-02-01", end: "2026-04-01", label: "Feb 1, 2026 – Mar 31, 2026" },
  series: [
    {
      id: "inflow",
      kind: "bar",
      label: "Inflow",
      result_id: "res_7f3b",
      points: [
        { x: "2026-02-01", y: "3200.00" },
        { x: "2026-03-01", y: "3200.00" },
      ],
    },
    {
      id: "outflow",
      kind: "bar",
      label: "Outflow",
      result_id: "res_7f3b",
      points: [
        { x: "2026-02-01", y: "2650.40" },
        { x: "2026-03-01", y: "3410.75" },
      ],
    },
    {
      id: "net",
      kind: "line",
      label: "Net",
      result_id: "res_7f3b",
      points: [
        { x: "2026-02-01", y: "549.60" },
        { x: "2026-03-01", y: "-210.75" },
      ],
    },
  ],
  annotations: [],
  assumptions: [{ key: "currency", label: "Currency", value: "USD", source: "default" }],
  sources: [source],
  table: {
    columns: ["Month", "Inflow", "Outflow", "Net"],
    rows: [
      ["Feb 2026", "3200.00", "2650.40", "549.60"],
      ["Mar 2026", "3200.00", "3410.75", "-210.75"],
    ],
  },
};

/** A template nothing has registered a renderer for: the frame must degrade safely. */
export const unknownTemplateSpec: ChartSpec = {
  ...swatchSpec,
  template_id: "<img src=x onerror=alert(1)>",
  title: "A template with no renderer",
};

export const emptySpec: ChartSpec = {
  ...swatchSpec,
  title: "Cash flow, 2020",
  table: { columns: swatchSpec.table.columns, rows: [] },
  series: [],
};
