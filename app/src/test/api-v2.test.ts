import { HttpEngineApi } from "../api/http";
import { MockEngineApi } from "../api/mock";

function fakeFetch(body: unknown) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ url: String(input), init: init ?? {} });
    return new Response(JSON.stringify(body), { status: 200 });
  }) as typeof fetch;
  return { fn, calls };
}

describe("v2 reader endpoints (HTTP client)", () => {
  it("fetches a batch of page fragments in one request", async () => {
    const page = { page: 2, mode: "tr", html: "", translated_blocks: 0, translatable_blocks: 0 };
    const { fn, calls } = fakeFetch({ pages: [page] });
    const api = new HttpEngineApi({ baseUrl: "http://127.0.0.1:5000", token: "t" }, fn);
    expect(await api.pagesHtml(1, [2, 3], "learn")).toEqual([page]);
    expect(calls[0]?.url).toBe("http://127.0.0.1:5000/api/books/1/html?pages=2%2C3&mode=learn");
    expect(await api.pagesHtml(1, [], "tr")).toEqual([]);
    expect(calls).toHaveLength(1);
  });

  it("estimate hint is a plain GET with the bearer token and no confirm token", async () => {
    const { fn, calls } = fakeFetch({ page: 5, calls: 1, usd: 0.02, seconds_hint: 10 });
    const api = new HttpEngineApi({ baseUrl: "http://x", token: "sekret" }, fn);
    const hint = await api.estimateHint(4, 5);
    expect(hint).not.toHaveProperty("confirm_token");
    expect(calls[0]?.url).toBe("http://x/api/books/4/pages/5/estimate_hint");
    expect(calls[0]?.init.method).toBe("GET");
    expect((calls[0]?.init.headers as Record<string, string>).Authorization).toBe("Bearer sekret");
  });
});

describe("v2 reader endpoints (mock)", () => {
  it("serves batches, sizes and hints without spending", async () => {
    const api = new MockEngineApi({ latencyMs: 0 });
    const book = await api.openBook("/books/sample.pdf");
    const pages = await api.pagesHtml(book.id, [3, 1, 3], "tr");
    expect(pages.map((p) => p.page)).toEqual([1, 3]);
    expect(pages[0]?.width).toBeGreaterThan(0);
    const hint = await api.estimateHint(book.id, 1);
    expect(hint.calls).toBe(1);
    expect((await api.usage()).calls).toBe(0);
    await expect(api.pagesHtml(book.id, Array.from({ length: 11 }, (_, i) => i + 1), "tr")).rejects.toMatchObject({
      kind: "bad_request",
    });
  });
});
