import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { Ask } from "./Ask";

afterEach(() => vi.unstubAllGlobals());

function stubAsk(answer: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify(answer))),
  );
}

it("posts the question and shows the grounded answer", async () => {
  stubAsk({ prose: "You spent $100.00.", grounded: true, unmatched: [], chart_spec: null });
  render(<Ask />);
  fireEvent.change(screen.getByTestId("ask-input"), { target: { value: "how much did I spend?" } });
  fireEvent.click(screen.getByTestId("ask-submit"));
  expect(await screen.findByTestId("ask-answer")).toHaveTextContent("You spent $100.00.");
  expect(fetch).toHaveBeenCalledWith("/ask", expect.objectContaining({ method: "POST" }));
});

it("notes when an unverified figure was withheld", async () => {
  stubAsk({ prose: "You spent $2,124.22.", grounded: false, unmatched: ["$500"], chart_spec: null });
  render(<Ask />);
  fireEvent.click(screen.getByText("Where did my money go?"));
  expect(await screen.findByTestId("grounding-note")).toBeInTheDocument();
});
