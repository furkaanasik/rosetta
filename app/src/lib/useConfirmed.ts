import { useCallback, useState } from "react";
import type { Estimate } from "../api/types";

export interface PendingAction<T> {
  estimate: Estimate;
  run: (token: string) => Promise<T>;
  onDone?: (result: T) => void;
}

/**
 * Two-step AI action: `request(estimateFn, runFn)` fetches the estimate and opens the
 * cost modal; `confirm()` runs it with the confirm token; `cancel()` discards it.
 */
export function useConfirmed(onError: (e: unknown) => void) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pending, setPending] = useState<PendingAction<any> | null>(null);
  const [busy, setBusy] = useState(false);

  const request = useCallback(
    async <T,>(
      estimateFn: () => Promise<Estimate>,
      run: (token: string) => Promise<T>,
      onDone?: (r: T) => void,
    ) => {
      try {
        setBusy(true);
        const estimate = await estimateFn();
        setPending({ estimate, run, onDone });
      } catch (e) {
        onError(e);
      } finally {
        setBusy(false);
      }
    },
    [onError],
  );

  const confirm = useCallback(async () => {
    if (!pending) return;
    setBusy(true);
    try {
      const result: unknown = await pending.run(pending.estimate.confirm_token);
      pending.onDone?.(result);
      setPending(null);
    } catch (e) {
      setPending(null);
      onError(e);
    } finally {
      setBusy(false);
    }
  }, [pending, onError]);

  const cancel = useCallback(() => setPending(null), []);

  return { pending, busy, request, confirm, cancel };
}
