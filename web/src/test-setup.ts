import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

// jsdom has no layout, so give chart containers a size for renderer tests.
vi.stubGlobal(
  "ResizeObserver",
  class {
    constructor(private cb: ResizeObserverCallback) {}
    observe(target: Element) {
      this.cb([{ target, contentRect: { width: 700, height: 320 } } as ResizeObserverEntry], this as never);
    }
    unobserve() {}
    disconnect() {}
  },
);
// Reduced motion: charts draw immediately (jsdom never advances animations), and the
// reduced-motion path gets exercised.
vi.stubGlobal("matchMedia", (query: string) => ({
  matches: query.includes("prefers-reduced-motion"),
  media: query,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
  onchange: null,
}));
Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 700 });
Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 320 });
