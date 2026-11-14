import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { Segmented } from "./Segmented";

const ITEMS = [
  { id: "3m", label: "3M", name: "Last 3 months" },
  { id: "6m", label: "6M", name: "Last 6 months" },
  { id: "all", label: "All", name: "All time" },
] as const;

function Harness() {
  const [value, setValue] = useState<(typeof ITEMS)[number]["id"]>("6m");
  return <Segmented label="Period" items={ITEMS} value={value} onChange={setValue} />;
}

describe("Segmented", () => {
  it("is a labelled radio group with one tab stop", () => {
    render(<Harness />);
    expect(screen.getByRole("radiogroup", { name: "Period" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Last 6 months" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getAllByRole("radio").filter((r) => r.tabIndex === 0)).toHaveLength(1);
  });

  it("moves the choice with arrow keys, wrapping, and keeps focus on it", () => {
    render(<Harness />);
    const six = screen.getByRole("radio", { name: "Last 6 months" });
    six.focus();
    fireEvent.keyDown(six, { key: "ArrowRight" });
    const all = screen.getByRole("radio", { name: "All time" });
    expect(all).toHaveAttribute("aria-checked", "true");
    expect(all).toHaveFocus();
    fireEvent.keyDown(all, { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "Last 3 months" })).toHaveAttribute("aria-checked", "true");
  });
});
