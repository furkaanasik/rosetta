import { MockEngineApi } from "../api/mock";

describe("MockEngineApi confirm tokens", () => {
  it("runs the AI only with a valid, one-shot token", async () => {
    const api = new MockEngineApi();
    const book = await api.openBook("/x/kitap.pdf");
    const est = await api.estimateTranslate(book.id, { pages: [1] });
    expect(api.aiCalls).toBe(0);
    await api.translate(book.id, est.confirm_token);
    expect(api.aiCalls).toBe(1);
    await expect(api.translate(book.id, est.confirm_token)).rejects.toMatchObject({ kind: "expired_token" });
  });

  it("a cached page estimates zero calls", async () => {
    const api = new MockEngineApi();
    const book = await api.openBook("/x/kitap.pdf");
    await api.translate(book.id, (await api.estimateTranslate(book.id, { pages: [2] })).confirm_token);
    const again = await api.estimateTranslate(book.id, { pages: [2] });
    expect(again.calls).toBe(0);
  });
});
