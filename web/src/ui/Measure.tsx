import { type ReactNode, useLayoutEffect, useRef, useState } from "react";

/** Measures its own width and renders its child once the width is known, so a chart is
 *  drawn at its real size (no fixed-width SVG scaled up or down). */
export function Measure({ children, minHeight }: { children: (width: number) => ReactNode; minHeight?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(0);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return (
    <div ref={ref} style={{ width: "100%", minHeight, position: "relative" }}>
      {width > 0 ? children(width) : null}
    </div>
  );
}
