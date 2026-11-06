import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import axe from "axe-core";
import { afterEach, beforeEach } from "vitest";
import { emptySpec, swatchSpec, unknownTemplateSpec } from "../dev/specs";
import { SwatchRenderer } from "../dev/SwatchRenderer";
import { clearRenderers, registerRenderer } from "../renderers/registry";
import { ChartFrame } from "./ChartFrame";

beforeEach(() => registerRenderer("fixture_swatch", SwatchRenderer));
afterEach(() => clearRenderers());

describe("ChartFrame", () => {
  it("shows the finding as a heading, the period, assumptions and sources", () => {
    render(<ChartFrame state={{ status: "ready", spec: swatchSpec }} />);

    expect(screen.getByRole("heading", { name: swatchSpec.title })).toBeInTheDocument();
    expect(screen.getByText(swatchSpec.period!.label)).toBeInTheDocument();
    expect(screen.getByText("Currency")).toBeInTheDocument();
    expect(screen.getByText(/cash_flow · res_7f3b · data dv_12/)).toBeInTheDocument();
  });

  it("carries the result ids for hover provenance", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: swatchSpec }} />);
    expect(container.querySelector("[data-result-ids]")).toHaveAttribute("title", "Source results: res_7f3b");
  });

  it("keeps the data table in the DOM for screen readers and toggles it for sighted users", async () => {
    render(<ChartFrame state={{ status: "ready", spec: swatchSpec }} />);

    const table = screen.getByRole("table", { name: /Cash flow, Feb–Mar 2026/ });
    expect(within(table).getByText("-210.75")).toBeInTheDocument();
    expect(table.parentElement).toHaveClass("sr-only");

    const toggle = screen.getByRole("button", { name: "Show data table" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(toggle);
    expect(screen.getByRole("button", { name: "Hide data table" })).toHaveAttribute("aria-pressed", "true");
    expect(table.parentElement).not.toHaveClass("sr-only");
  });

  it("is operable from the keyboard", async () => {
    render(<ChartFrame state={{ status: "ready", spec: swatchSpec }} />);
    await userEvent.tab();
    expect(screen.getByRole("button", { name: "Show data table" })).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: "Hide data table" })).toBeInTheDocument();
  });

  it("degrades safely for a template with no renderer: data as a table, no markup injection", () => {
    const { container } = render(<ChartFrame state={{ status: "ready", spec: unknownTemplateSpec }} />);

    expect(screen.getByRole("alert")).toHaveTextContent("no chart for “<img src=x onerror=alert(1)>” yet");
    expect(container.querySelector("img")).toBeNull();
    expect(screen.queryByRole("button", { name: /data table/ })).toBeNull();
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("renders loading, empty and error states", () => {
    const { rerender } = render(<ChartFrame state={{ status: "loading" }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading chart");

    rerender(<ChartFrame state={{ status: "ready", spec: emptySpec }} />);
    expect(screen.getByRole("status")).toHaveTextContent("No data for this period.");
    expect(screen.queryByRole("table")).toBeNull();

    rerender(<ChartFrame state={{ status: "error", message: "HTTP 422" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP 422");
  });

  it("marks negative money with a glyph and text, not color alone", () => {
    render(<ChartFrame state={{ status: "ready", spec: swatchSpec }} />);
    const negatives = screen.getAllByText("−$210.75");
    expect(negatives.length).toBeGreaterThan(0);
    const wrapper = negatives[0]!.closest(".money")!;
    expect(wrapper).toHaveAttribute("data-sign", "negative");
    expect(wrapper).toHaveTextContent("▼");
    expect(within(wrapper as HTMLElement).getByText("(negative)")).toBeInTheDocument();
  });

  it("has no axe violations in any state", async () => {
    const { container } = render(
      <>
        <ChartFrame state={{ status: "ready", spec: swatchSpec }} />
        <ChartFrame state={{ status: "ready", spec: unknownTemplateSpec }} />
        <ChartFrame state={{ status: "ready", spec: emptySpec }} />
        <ChartFrame state={{ status: "loading" }} />
        <ChartFrame state={{ status: "error", message: "x" }} />
      </>,
    );
    const results = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } }, // jsdom has no layout or CSS vars
    });
    expect(results.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
  });
});
