// @vitest-environment node
// Optional end-to-end check of HttpEngineApi against a real `rosetta serve`.
// Runs only when ROSETTA_ENGINE_URL is set; start the engine with provider = "fake" in its
// config.toml so no AI provider is ever called, e.g.:
//   ROSETTA_DATA_DIR=/tmp/r/data ROSETTA_CONFIG_DIR=/tmp/r/cfg uv run rosetta serve --token test
//   ROSETTA_ENGINE_URL=http://127.0.0.1:<port> ROSETTA_ENGINE_TOKEN=test \
//     ROSETTA_TEST_PDF=/path/book.pdf npx vitest run src/api/http.integration.test.ts
import { describe, expect, it } from "vitest";
import { HttpEngineApi } from "./http";
import { EngineError } from "./types";

const baseUrl = process.env.ROSETTA_ENGINE_URL;
const token = process.env.ROSETTA_ENGINE_TOKEN ?? "";
const pdf = process.env.ROSETTA_TEST_PDF;

describe.skipIf(!baseUrl || !pdf)("HttpEngineApi ↔ rosetta serve", () => {
  const api = new HttpEngineApi({ baseUrl: baseUrl ?? "", token });

  it("rejects a wrong token with an EngineError", async () => {
    const bad = new HttpEngineApi({ baseUrl: baseUrl ?? "", token: "wrong" });
    await expect(bad.health()).rejects.toMatchObject({ kind: "unauthorized", status: 401 });
  });

  it("opens a book, reads blocks/HTML, translates via confirm token, learns", async () => {
    expect((await api.health()).ok).toBe(true);
    const book = await api.openBook(pdf ?? "");
    expect(book.page_count).toBeGreaterThan(0);

    const blocks = await api.pageBlocks(book.id, 1);
    const html = await api.pageHtml(book.id, 1, "tr");
    for (const b of blocks.blocks.filter((x) => x.type !== "furniture" && x.type !== "footnote")) {
      expect(html.html).toContain(`data-block="${b.key}"`);
    }

    await expect(api.translate(book.id, "forged")).rejects.toMatchObject({
      kind: "expired_token",
    });
    const est = await api.estimateTranslate(book.id, { pages: [1] });
    expect(est.operation).toBe("translate");
    const report = await api.translate(book.id, est.confirm_token);
    expect(report.done_pages).toEqual([1]);
    await expect(api.translate(book.id, est.confirm_token)).rejects.toBeInstanceOf(EngineError);

    const again = await api.estimateTranslate(book.id, { pages: [1] });
    expect(again.calls).toBe(0);

    const item = await api.addVocab({ word: "replication", book_id: book.id, page: 1 });
    expect(item.page).toBe(1);
    expect((await api.stats()).total_words).toBeGreaterThan(0);
    expect((await api.usage(book.id)).calls).toBeGreaterThan(0);
    await api.deleteVocab(item.id);
  });
});
