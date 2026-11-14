import { motion } from "motion/react";
import { type KeyboardEvent, useId, useRef } from "react";
import { useCalm } from "./motion";

export interface SegmentedItem<T extends string> {
  id: T;
  label: string;
  /** Longer accessible name when the label is an abbreviation ("6M"). */
  name?: string;
}

/** A single-choice control (radio group) with a sliding selection pill. Arrow keys move
 *  the choice, as in a native radio group. */
export function Segmented<T extends string>({
  items,
  value,
  onChange,
  label,
}: {
  items: readonly SegmentedItem<T>[];
  value: T;
  onChange: (value: T) => void;
  label: string;
}) {
  const calm = useCalm();
  const group = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (event: KeyboardEvent, index: number) => {
    const step = event.key === "ArrowRight" || event.key === "ArrowDown" ? 1 : event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + items.length) % items.length;
    const item = items[next];
    if (!item) return;
    onChange(item.id);
    refs.current[next]?.focus();
  };
  return (
    <div className="tabs" role="radiogroup" aria-label={label}>
      {items.map((item, index) => {
        const selected = item.id === value;
        return (
          <button
            key={item.id}
            ref={(el) => {
              refs.current[index] = el;
            }}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={item.name}
            tabIndex={selected ? 0 : -1}
            className="tab"
            onClick={() => onChange(item.id)}
            onKeyDown={(event) => onKey(event, index)}
          >
            {selected && (
              <motion.span
                layoutId={`pill-${group}`}
                className="tab-pill"
                transition={calm ? { duration: 0 } : { type: "spring", duration: 0.3, bounce: 0 }}
              />
            )}
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
