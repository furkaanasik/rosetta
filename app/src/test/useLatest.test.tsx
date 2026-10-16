import { act, renderHook } from "@testing-library/react";
import { useLatest } from "../lib/useLatest";

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe("useLatest", () => {
  it("ignores a slower, older response", async () => {
    const { result } = renderHook(() => useLatest());
    const applied: string[] = [];
    const first = deferred<string>();
    const second = deferred<string>();

    const p1 = result.current(first.promise, (v) => applied.push(v));
    const p2 = result.current(second.promise, (v) => applied.push(v));
    await act(async () => {
      second.resolve("new");
      first.resolve("old");
      await Promise.all([p1, p2]);
    });

    expect(applied).toEqual(["new"]);
  });

  it("drops responses after unmount", async () => {
    const { result, unmount } = renderHook(() => useLatest());
    const applied: string[] = [];
    const d = deferred<string>();
    const p = result.current(d.promise, (v) => applied.push(v));

    unmount();
    d.resolve("late");
    await p;

    expect(applied).toEqual([]);
  });
});
