import { useReducedMotion } from "motion/react";

/** Strong ease-out: fast start, gentle settle (UI motion stays under ~300 ms; chart
 *  entrances, once per load, get 600 ms). */
export const EASE_OUT = [0.23, 1, 0.32, 1] as const;
export const SPRING = { type: "spring", duration: 0.55, bounce: 0 } as const;

/** True when the OS asks for reduced motion. Charts then draw in place, numbers swap
 *  instead of rolling, and nothing slides. */
export function useCalm(): boolean {
  return useReducedMotion() ?? false;
}
