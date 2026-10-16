import { initialPdf, onEngineError, onOpenPdf, waitForEngine } from "../lib/engineConnect";

describe("initialPdf (browser)", () => {
  it("reads ?open=", async () => {
    expect(await initialPdf("?open=/home/u/kitap.pdf")).toBe("/home/u/kitap.pdf");
  });

  it("returns null without a path", async () => {
    expect(await initialPdf("")).toBeNull();
    expect(await initialPdf("?open=%20")).toBeNull();
  });

  it("has no hand-over listener outside Tauri", async () => {
    const unlisten = await onOpenPdf(() => undefined);
    expect(typeof unlisten).toBe("function");
    unlisten();
  });
});

describe("waitForEngine", () => {
  const info = { baseUrl: "http://127.0.0.1:1", token: "t" };

  it("keeps polling until the engine reports its address", async () => {
    let n = 0;
    const got = await waitForEngine(async () => (++n < 3 ? null : info), 10, 1);
    expect(got).toEqual(info);
    expect(n).toBe(3);
  });

  it("gives up after the given number of tries", async () => {
    expect(await waitForEngine(async () => null, 3, 1)).toBeNull();
  });

  it("surfaces the engine's start-up error", async () => {
    await expect(waitForEngine(async () => Promise.reject(new Error("Motor bulunamadı")), 5, 1)).rejects.toThrow("Motor bulunamadı");
  });

  it("stops waiting as soon as it is woken", async () => {
    let ready = false;
    let wake: () => void = () => undefined;
    const woken = new Promise<void>((r) => (wake = r));
    const started = Date.now();
    const p = waitForEngine(async () => (ready ? info : null), 5, 10_000, woken);
    ready = true;
    wake();
    expect(await p).toEqual(info);
    expect(Date.now() - started).toBeLessThan(2000);
  });

  it("has no engine-error listener outside Tauri", async () => {
    const unlisten = await onEngineError(() => undefined);
    unlisten();
  });
});
