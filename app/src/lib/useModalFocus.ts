import { useEffect, useRef, type RefObject } from "react";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Modal keyboard behaviour: Escape anywhere in the document calls `onEscape`, Tab cycles
 * inside the dialog, and focus returns to the element that opened it.
 */
export function useModalFocus(
  dialog: RefObject<HTMLElement | null>,
  onEscape: () => void,
  initialFocus?: RefObject<HTMLElement | null>,
): void {
  const escape = useRef(onEscape);
  escape.current = onEscape;

  useEffect(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    (initialFocus?.current ?? dialog.current)?.focus();

    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        escape.current();
        return;
      }
      if (e.key !== "Tab" || !dialog.current) return;
      const items = Array.from(dialog.current.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (items.length === 0) {
        e.preventDefault();
        dialog.current.focus();
        return;
      }
      const first = items[0]!;
      const last = items[items.length - 1]!;
      const active = document.activeElement;
      const inside = active instanceof Node && dialog.current.contains(active);
      if (e.shiftKey && (active === first || !inside)) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && (active === last || !inside)) {
        e.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      if (opener && document.contains(opener)) opener.focus();
    };
    // Mount/unmount only: the dialog element and opener are fixed for one modal's lifetime.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
}
