import { useEffect, useRef } from "react";

/** Key → handler. Keys: "k", "1", "arrowleft", "pagedown", "\\", "escape"; prefix "mod+" for Ctrl/⌘. */
export type ShortcutMap = Record<string, (e: KeyboardEvent) => void>;

function typing(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || target.isContentEditable;
}

/** Normalised key name for a keyboard event, e.g. "mod+k", "arrowright", "=". */
export function keyName(e: KeyboardEvent): string {
  const key = e.key.length === 1 ? e.key.toLowerCase() : e.key.toLowerCase();
  return (e.ctrlKey || e.metaKey ? "mod+" : "") + key;
}

/**
 * Global reader shortcuts. Plain keys are ignored while typing in a field and while a modal
 * dialog (cost confirmation, palette…) is open — the dialog owns the keyboard then.
 */
export function useShortcuts(map: ShortcutMap, enabled = true): void {
  const ref = useRef(map);
  ref.current = map;
  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.altKey) return;
      const name = keyName(e);
      const handler = ref.current[name];
      if (!handler) return;
      const plain = !name.startsWith("mod+");
      if (plain && typing(e.target)) return;
      if (document.querySelector('[aria-modal="true"]')) return;
      e.preventDefault();
      handler(e);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled]);
}
