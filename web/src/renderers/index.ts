import { CashFlowRenderer } from "./CashFlowRenderer";
import { CategoryTrendsRenderer } from "./CategoryTrendsRenderer";
import { KpiRenderer } from "./KpiRenderer";
import { getRenderer, registerRenderer, type Renderer } from "./registry";
import { SpendBreakdownRenderer } from "./SpendBreakdownRenderer";
import { SpendOverTimeRenderer } from "./SpendOverTimeRenderer";

// `clarify` has no renderer: ChartFrame shows it as a question with options.
const ALL: Record<string, Renderer> = {
  cash_flow: CashFlowRenderer,
  spend_over_time: SpendOverTimeRenderer,
  spend_breakdown: SpendBreakdownRenderer,
  kpi: KpiRenderer,
  category_trends: CategoryTrendsRenderer,
};

/** Registers every real template renderer. Safe to call more than once. */
export function registerAllRenderers(): void {
  for (const [id, renderer] of Object.entries(ALL)) {
    if (!getRenderer(id)) registerRenderer(id, renderer);
  }
}
