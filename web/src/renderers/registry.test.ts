import { afterEach } from "vitest";
import { clearRenderers, getRenderer, registerRenderer } from "./registry";

afterEach(() => clearRenderers());

describe("renderer registry", () => {
  it("maps template ids to renderers and rejects duplicates", () => {
    const renderer = () => null;
    registerRenderer("cash_flow", renderer);

    expect(getRenderer("cash_flow")).toBe(renderer);
    expect(getRenderer("nope")).toBeUndefined();
    expect(() => registerRenderer("cash_flow", renderer)).toThrow(/already registered/);
  });
});
