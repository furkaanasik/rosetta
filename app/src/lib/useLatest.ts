import { useCallback, useEffect, useRef } from "react";

/**
 * "Latest request wins": `latest(promise, apply)` applies the result only if no newer request
 * was started since and the component is still mounted. Stops slow, out-of-order responses
 * (e.g. a previous book's list or a superseded search) from overwriting fresher state.
 */
export function useLatest(): <T>(p: Promise<T>, apply: (value: T) => void) => Promise<void> {
  const seq = useRef(0);
  useEffect(() => {
    const ref = seq;
    return () => {
      ref.current++;
    };
  }, []);
  return useCallback(<T,>(p: Promise<T>, apply: (value: T) => void) => {
    const id = ++seq.current;
    return p.then((value) => {
      if (id === seq.current) apply(value);
    });
  }, []);
}
