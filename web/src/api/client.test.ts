import { afterEach, vi } from "vitest";
import { renderChart } from "./client";

afterEach(() => vi.unstubAllGlobals());

const respond = (status: number, body: unknown) =>
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(body), { status })));

describe("renderChart", () => {
  it("posts the template and params to the same-origin render route", async () => {
    respond(200, { template_id: "cash_flow" });

    await renderChart("cash_flow", { period: { preset: "last_month" } });

    const [url, init] = vi.mocked(fetch).mock.calls[0]!;
    expect(url).toBe("/charts/render");
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({
      template_id: "cash_flow",
      params: { period: { preset: "last_month" } },
    });
  });

  it("explains a 422 with the failing field", async () => {
    respond(422, { detail: [{ loc: ["params", "period", "preset"], msg: "Input should be 'this_month'" }] });

    await expect(renderChart("cash_flow", {})).rejects.toThrow(
      "422: params.period.preset: Input should be 'this_month'",
    );
  });

  it("explains a string detail and an unreadable failure", async () => {
    respond(404, { detail: "unknown template 'x'" });
    await expect(renderChart("x", {})).rejects.toThrow("404: unknown template 'x'");

    vi.stubGlobal("fetch", vi.fn(async () => new Response("<html>", { status: 502 })));
    await expect(renderChart("x", {})).rejects.toThrow("HTTP 502");
  });
});
