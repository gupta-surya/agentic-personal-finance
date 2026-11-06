import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { App } from "./App";

afterEach(() => vi.unstubAllGlobals());

/** /charts/meta answers as given; any render request fails, which is fine for these tests. */
function stubApi(meta: () => Response) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => (url === "/charts/meta" ? meta() : new Response("{}", { status: 500 }))),
  );
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

  it("shows no label, and still renders, when the source cannot be read", async () => {
    stubApi(() => new Response("nope", { status: 503 }));
    render(<App />);

    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/charts/meta"));
    expect(screen.queryByTestId("data-source")).toBeNull();
    expect(screen.getByRole("heading", { name: "Charts" })).toBeInTheDocument();
  });
});
