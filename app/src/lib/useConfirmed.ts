import { useCallback, useRef, useState } from "react";
import type { Estimate } from "../api/types";

export interface PendingAction<T> {
  estimate: Estimate;
  run: (token: string) => Promise<T>;
  onDone?: (result: T) => void;
}

/**
 * Two-step AI action: `request(estimateFn, runFn)` fetches the estimate and opens the
 * cost modal; `confirm()` runs it with the confirm token; `cancel()` discards it.
 *
 * While an estimate is shown (or loading, or running) further requests are ignored, so the
 * estimate the user is looking at can never be swapped under their "Onayla" click; and a
 * running call can't be "cancelled" (it would keep running and spending in the background).
 */
export function useConfirmed(onError: (e: unknown) => void) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const [pending, setPending] = useState<PendingAction<any> | null>(null);
  const [busy, setBusy] = useState(false);
  const locked = useRef(false); // an estimate is loading or shown
  const running = useRef(false); // the confirmed call is in flight

  const request = useCallback(
    async <T,>(
      estimateFn: () => Promise<Estimate>,
      run: (token: string) => Promise<T>,
      onDone?: (r: T) => void,
    ) => {
      if (locked.current) return;
      locked.current = true;
      try {
        setBusy(true);
        const estimate = await estimateFn();
        setPending({ estimate, run, onDone });
      } catch (e) {
        locked.current = false;
        onError(e);
      } finally {
        setBusy(false);
      }
    },
    [onError],
  );

  const confirm = useCallback(async () => {
    if (!pending || running.current) return;
    running.current = true;
    setBusy(true);
    try {
      const result: unknown = await pending.run(pending.estimate.confirm_token);
      pending.onDone?.(result);
    } catch (e) {
      onError(e);
    } finally {
      running.current = false;
      locked.current = false;
      setPending(null);
      setBusy(false);
    }
  }, [pending, onError]);

  const cancel = useCallback(() => {
    if (running.current) return;
    locked.current = false;
    setPending(null);
  }, []);

  return { pending, busy, request, confirm, cancel };
}
