import { CashFlowRenderer } from "./CashFlowRenderer";
import { getRenderer, registerRenderer } from "./registry";

/** Registers every real template renderer. Safe to call more than once. */
export function registerAllRenderers(): void {
  const all = { cash_flow: CashFlowRenderer };
  for (const [id, renderer] of Object.entries(all)) {
    if (!getRenderer(id)) registerRenderer(id, renderer);
  }
}
