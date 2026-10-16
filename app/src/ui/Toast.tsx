import { CheckCircle, Info, WarningCircle, X } from "@phosphor-icons/react";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { cx } from "./cx";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface ToastInput {
  message: string;
  tone?: ToastTone;
  action?: { label: string; onClick: () => void };
  /** ms; default 4 s (errors 8 s). */
  duration?: number;
}

interface ToastItem extends ToastInput {
  id: number;
}

/** Shows a toast; returns a function that dismisses it early. */
type Show = (t: ToastInput | string) => () => void;

const ToastContext = createContext<Show>(() => () => undefined);

/** `toast("Sayfa çevrildi")` / `toast({ message, tone: "error" })`. */
export function useToast(): Show {
  return useContext(ToastContext);
}

const ICON: Record<ToastTone, ReactNode> = {
  info: <Info weight="regular" />,
  success: <CheckCircle weight="regular" />,
  warning: <WarningCircle weight="regular" />,
  error: <WarningCircle weight="fill" />,
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const seq = useRef(0);
  const timers = useRef(new Map<number, number>());

  const dismiss = useCallback((id: number) => {
    window.clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setItems((list) => list.filter((t) => t.id !== id));
  }, []);

  const show = useCallback<Show>(
    (input) => {
      const t: ToastInput = typeof input === "string" ? { message: input } : input;
      const id = ++seq.current;
      const tone = t.tone ?? "info";
      // At most three on screen; the oldest goes first.
      setItems((list) => [...list.slice(-2), { ...t, tone, id }]);
      timers.current.set(id, window.setTimeout(() => dismiss(id), t.duration ?? (tone === "error" ? 8000 : 4000)));
      return () => dismiss(id);
    },
    [dismiss],
  );

  useEffect(() => {
    const map = timers.current;
    return () => map.forEach((h) => window.clearTimeout(h));
  }, []);

  const value = useMemo(() => show, [show]);
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cx("toast", `toast--${t.tone}`)}>
            <span className="toast__icon" aria-hidden="true">
              {ICON[t.tone ?? "info"]}
            </span>
            <span className="toast__text">{t.message}</span>
            {t.action && (
              <button
                type="button"
                className="toast__action"
                onClick={() => {
                  t.action?.onClick();
                  dismiss(t.id);
                }}
              >
                {t.action.label}
              </button>
            )}
            <button type="button" className="toast__close" aria-label="Bildirimi kapat" onClick={() => dismiss(t.id)}>
              <X aria-hidden="true" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
