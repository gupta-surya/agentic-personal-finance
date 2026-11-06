import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { vi } from "vitest";
import type { ChartSpec } from "../api/types";
import { swatchSpec } from "../fixtures/specs";
import { ChartFrame } from "./ChartFrame";

const spec: ChartSpec = {
  ...swatchSpec,
  template_id: "clarify",
  title: "Which view of your spending do you want?",
  period: null,
  series: [],
  sources: [],
  assumptions: [],
  table: { columns: [], rows: [] },
  clarify: {
    question: "Which view of your spending do you want?",
    options: [
      { label: "Where it went", template_id: "spend_breakdown", params: { period: { preset: "last_6_months" } } },
      { label: "How it changed", template_id: "spend_over_time", params: { period: { preset: "last_6_months" } } },
    ],
  },
};

describe("clarify card", () => {
  it("shows the question as a heading and each option as a button", () => {
    render(<ChartFrame state={{ status: "ready", spec }} onChoose={() => {}} />);

    expect(screen.getByRole("heading", { name: spec.clarify!.question })).toBeInTheDocument();
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Where it went", "How it changed"]);
  });

  it("sends the chosen option's ready request on a pointer click", async () => {
    const onChoose = vi.fn();
    render(<ChartFrame state={{ status: "ready", spec }} onChoose={onChoose} />);

    await userEvent.click(screen.getByRole("button", { name: "How it changed" }));

    expect(onChoose).toHaveBeenCalledOnce();
    expect(onChoose).toHaveBeenCalledWith("spend_over_time", { period: { preset: "last_6_months" } });
  });

  it("is operable from the keyboard: Tab to a chip, then Enter or Space", async () => {
    const onChoose = vi.fn();
    render(<ChartFrame state={{ status: "ready", spec }} onChoose={onChoose} />);

    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Where it went" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "How it changed" })).toHaveFocus();
    await userEvent.keyboard(" ");

    expect(onChoose.mock.calls.map(([id]) => id)).toEqual(["spend_breakdown", "spend_over_time"]);
  });

  it("does nothing, and says so, when nothing is listening", () => {
    render(<ChartFrame state={{ status: "ready", spec }} />);
    for (const button of screen.getAllByRole("button")) expect(button).toBeDisabled();
  });

  it("has no axe violations", async () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec }} onChoose={() => {}} />);
    const results = await axe.run(container, { rules: { "color-contrast": { enabled: false } } });
    expect(results.violations.map((v) => v.id)).toEqual([]);
  });
});
