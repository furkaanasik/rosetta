import * as Tabs from "@radix-ui/react-tabs";
import type { CSSProperties, ReactNode } from "react";

export interface SegmentedItem<T extends string> {
  value: T;
  label: string;
  icon?: ReactNode;
  /** Shortcut hint shown in the tooltip, e.g. "1". */
  shortcut?: string;
}

interface Props<T extends string> {
  label: string;
  value: T;
  items: SegmentedItem<T>[];
  onChange: (value: T) => void;
  className?: string;
}

/**
 * Segmented control with a sliding chip. Built on Radix Tabs (arrow keys, roving focus);
 * every segment has the same width, so the chip just translates by its index.
 */
export function Segmented<T extends string>({ label, value, items, onChange, className }: Props<T>) {
  const index = Math.max(0, items.findIndex((i) => i.value === value));
  const style = { "--seg-count": items.length, "--seg-index": index } as CSSProperties;
  return (
    <Tabs.Root value={value} onValueChange={(v) => onChange(v as T)} activationMode="automatic">
      <Tabs.List aria-label={label} className={`segmented${className ? ` ${className}` : ""}`} style={style}>
        <span className="segmented__chip" aria-hidden="true" />
        {items.map((it) => (
          <Tabs.Trigger
            key={it.value}
            value={it.value}
            className="segmented__item"
            title={it.shortcut ? `${it.label} (${it.shortcut})` : it.label}
          >
            {it.icon && (
              <span className="segmented__icon" aria-hidden="true">
                {it.icon}
              </span>
            )}
            <span className="segmented__label">{it.label}</span>
          </Tabs.Trigger>
        ))}
      </Tabs.List>
    </Tabs.Root>
  );
}
