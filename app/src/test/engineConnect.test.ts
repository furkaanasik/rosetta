import { initialPdf, onOpenPdf } from "../lib/engineConnect";

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
