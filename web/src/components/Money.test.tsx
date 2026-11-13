import { render } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { FlowFigure } from "./Money";

// motion reads the OS setting once per page, so the test controls our hook directly.
const calm = vi.hoisted(() => ({ value: true }));
vi.mock("../ui/motion", () => ({ useCalm: () => calm.value }));
const motionAllowed = () => {
  calm.value = false;
};

afterEach(() => {
  calm.value = true;
});

describe("FlowFigure", () => {
  it("is the exact string, statically, under reduced motion", () => {
    const { container } = render(<FlowFigure amount="14609.67" />);
    expect(container).toHaveTextContent("$14,609.67");
    expect(container.querySelector("number-flow-react")).toBeNull();
  });

  it("rolls digits only when formatting the number reproduces the exact string", () => {
    motionAllowed();
    const { container } = render(<FlowFigure amount="14609.67" />);
    const wrapper = container.querySelector("[data-exact]")!;
    expect(wrapper).toHaveAttribute("data-exact", "$14,609.67");
    // Screen readers get the exact string, not the animation.
    expect(wrapper.querySelector(".sr-only")).toHaveTextContent("$14,609.67");
  });

  it("falls back to the exact string when Intl would round it", () => {
    motionAllowed();
    const { container } = render(<FlowFigure amount="0.125" />);
    expect(container.querySelector("[data-exact]")).toBeNull();
    expect(container).toHaveTextContent("$0.125");
  });

  it("never animates a negative amount; it keeps its sign and glyph", () => {
    motionAllowed();
    const { container } = render(<FlowFigure amount="-1281.29" />);
    expect(container.querySelector("[data-exact]")).toBeNull();
    expect(container).toHaveTextContent("▼ −$1,281.29");
  });
});
