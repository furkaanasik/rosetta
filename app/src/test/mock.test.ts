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

describe("MockEngineApi term consistency", () => {
  it("accepting a term edits the glossary without AI; targeted re-translation needs a token", async () => {
    const api = new MockEngineApi();
    const book = await api.openBook("/x/kitap.pdf");
    const report = await api.consistency(book.id);
    expect(report.issues.map((i) => i.term)).toEqual(["leader", "replication"]);

    const res = await api.acceptTerm(book.id, "replication", "çoğaltma");
    expect(res.profile.sozluk.replication).toBe("çoğaltma");
    expect(res.affected_count).toBe(3);
    expect(api.aiCalls).toBe(0);

    const est = await api.estimateTranslate(book.id, { pages: [], blocks: res.affected });
    expect(est.pages).toEqual([4, 5, 6]);
    expect(api.aiCalls).toBe(0);
    await api.translate(book.id, est.confirm_token);
    expect(api.aiCalls).toBe(1);
  });
});
