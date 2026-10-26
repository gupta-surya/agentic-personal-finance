import type { ReactNode } from "react";
import type { ChartSpec } from "../api/types";

/** Draws one template. It receives a finished ChartSpec and never fetches or computes
 *  money: it copies, orders and formats values that are already in the spec. */
export type Renderer = (props: { spec: ChartSpec }) => ReactNode;

const renderers = new Map<string, Renderer>();

export function registerRenderer(templateId: string, renderer: Renderer): void {
  if (renderers.has(templateId)) throw new Error(`renderer for ${templateId} already registered`);
  renderers.set(templateId, renderer);
}

export function getRenderer(templateId: string): Renderer | undefined {
  return renderers.get(templateId);
}

/** For tests only. */
export function clearRenderers(): void {
  renderers.clear();
}
