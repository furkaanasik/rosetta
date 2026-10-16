import { useCallback, useEffect, useRef } from "react";

/**
 * "Latest request wins": `latest(promise, apply)` applies the result only if no newer request
 * was started since and the component is still mounted. Stops slow, out-of-order responses
 * (e.g. a previous book's list or a superseded search) from overwriting fresher state.
 * Rejections go to `onError` (latest request only) and are never left unhandled.
 */
export function useLatest(): <T>(
  p: Promise<T>,
  apply: (value: T) => void,
  onError?: (e: unknown) => void,
) => Promise<void> {
  const seq = useRef(0);
  useEffect(() => {
    const ref = seq;
    return () => {
      ref.current++;
    };
  }, []);
  return useCallback(<T,>(p: Promise<T>, apply: (value: T) => void, onError?: (e: unknown) => void) => {
    const id = ++seq.current;
    return p.then(
      (value) => {
        if (id === seq.current) apply(value);
      },
      (e: unknown) => {
        // Errors of superseded requests are irrelevant; never leave a rejection unhandled.
        if (id === seq.current) onError?.(e);
      },
    );
  }, []);
}
