import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { App } from "./App";

afterEach(() => {
  vi.unstubAllGlobals();
  window.location.hash = "";
});

/** /charts/meta answers as given; any render request fails, which is fine for these tests. */
function stubApi(meta: () => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => (url === "/charts/meta" ? meta() : new Response("{}", { status: 500 }))),
  );
}

function goto(hash: string) {
  window.location.hash = hash;
  window.dispatchEvent(new HashChangeEvent("hashchange"));
}

describe("data source label", () => {
  it("says Your data when the API serves Postgres", async () => {
    stubApi(() => new Response(JSON.stringify({ source: "postgres" })));
    render(<App />);
    expect(await screen.findByTestId("data-source")).toHaveTextContent("Your data");
  });

  it("says Synthetic data when the API serves the fake catalog", async () => {
    stubApi(() => new Response(JSON.stringify({ source: "synthetic" })));
    render(<App />);
    expect(await screen.findByTestId("data-source")).toHaveTextContent("Synthetic data");
  });

  it("shows no label, and still renders Ask as the home, when the source cannot be read", async () => {
    stubApi(() => new Response("nope", { status: 503 }));
    render(<App />);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/charts/meta"));
    expect(screen.queryByTestId("data-source")).toBeNull();
    expect(screen.getByRole("heading", { level: 1, name: "Ask" })).toBeInTheDocument();
    expect(screen.getByLabelText("Ask about your spending")).toBeInTheDocument();
  });
});

describe("navigation", () => {
  it("opens on Ask and marks it current", () => {
    stubApi(() => new Response(JSON.stringify({ source: "synthetic" })));
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Ask" })).toBeInTheDocument();
    const main = screen.getByRole("navigation", { name: "Main" });
    expect(within(main).getByRole("link", { name: "Ask" })).toHaveAttribute("aria-current", "page");
  });

  it("moves between dashboard pages by hash and marks the current one", async () => {
    stubApi(() => new Response(JSON.stringify({ source: "synthetic" })));
    render(<App />);

    goto("#/spending");
    expect(await screen.findByRole("heading", { level: 1, name: "Spending" })).toBeInTheDocument();
    const main = screen.getByRole("navigation", { name: "Main" });
    expect(within(main).getByRole("link", { name: "Spending" })).toHaveAttribute("aria-current", "page");

    goto("#/overview");
    expect(await screen.findByRole("heading", { level: 1, name: "Overview" })).toBeInTheDocument();
  });

  it("offers the period and currency controls on a dashboard page, not on Ask", async () => {
    stubApi(() => new Response(JSON.stringify({ source: "synthetic" })));
    render(<App />);
    // Ask home has no period/currency controls.
    expect(screen.queryByRole("radiogroup", { name: "Period" })).toBeNull();

    goto("#/overview");
    expect(await screen.findByRole("radiogroup", { name: "Period" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Last 6 months" })).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("combobox", { name: "Currency" })).toHaveValue("USD");
  });
});
