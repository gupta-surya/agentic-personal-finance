import { afterEach, vi } from "vitest";
import { applyAccent, applyTheme, loadAccent, loadTheme } from "./prefs";

afterEach(() => {
  vi.restoreAllMocks();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-accent");
  window.localStorage.clear();
});

describe("display preferences", () => {
  it("applies and remembers the theme and accent", () => {
    applyTheme("dark");
    applyAccent("forest");
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");
    expect(document.documentElement).toHaveAttribute("data-accent", "forest");
    expect(loadTheme()).toBe("dark");
    expect(loadAccent()).toBe("forest");

    applyTheme("system");
    applyAccent("indigo");
    expect(document.documentElement).not.toHaveAttribute("data-theme");
    expect(document.documentElement).not.toHaveAttribute("data-accent");
  });

  it("ignores unknown stored values and falls back to the defaults", () => {
    window.localStorage.setItem("fa.theme", "sepia");
    window.localStorage.setItem("fa.accent", "javascript:alert(1)");
    expect(loadTheme()).toBe("system");
    expect(loadAccent()).toBe("indigo");
  });

  it("still works when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(loadTheme()).toBe("system");
    expect(() => applyAccent("plum")).not.toThrow();
    expect(document.documentElement).toHaveAttribute("data-accent", "plum");
  });
});
