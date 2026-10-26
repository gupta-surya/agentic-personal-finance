import type { ChartSpec } from "./types";

/** POST /charts/render on the same origin (Vite proxies it to the local API in dev).
 *  Never calls anything else, and never another origin. */
export async function renderChart(
  templateId: string,
  params: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<ChartSpec> {
  const response = await fetch("/charts/render", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ template_id: templateId, params }),
    signal,
  });
  if (!response.ok) throw new Error(await describeFailure(response));
  return (await response.json()) as ChartSpec;
}

async function describeFailure(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as { detail?: unknown };
    const detail = body.detail;
    if (typeof detail === "string") return `${response.status}: ${detail}`;
    if (Array.isArray(detail)) {
      const parts = detail.map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).join(".")}: ${d.msg ?? ""}`);
      return `${response.status}: ${parts.join("; ")}`;
    }
  } catch {
    // fall through to the status line
  }
  return `The render request failed (HTTP ${response.status}).`;
}
