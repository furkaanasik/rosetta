import { HttpEngineApi } from "../api/http";
import { EngineError } from "../api/types";

function fakeFetch(handler: (url: string, init: RequestInit) => { status: number; body?: unknown }) {
  const calls: { url: string; init: RequestInit }[] = [];
  const fn = (async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init: init ?? {} });
    const r = handler(url, init ?? {});
    return new Response(r.body === undefined ? null : JSON.stringify(r.body), { status: r.status });
  }) as typeof fetch;
  return { fn, calls };
}

describe("HttpEngineApi", () => {
  it("sends bearer token, JSON body and query params", async () => {
    const { fn, calls } = fakeFetch(() => ({ status: 200, body: { page: 3, mode: "tr", html: "", translated_blocks: 0, translatable_blocks: 0 } }));
    const api = new HttpEngineApi({ baseUrl: "http://127.0.0.1:5000/", token: "sekret" }, fn);
    await api.pageHtml(1, 3, "tr", "tr");
    await api.translate(1, "tok-1");
    expect(calls[0]?.url).toBe("http://127.0.0.1:5000/api/books/1/pages/3/html?mode=tr&lang=tr");
    expect((calls[0]?.init.headers as Record<string, string>).Authorization).toBe("Bearer sekret");
    expect(calls[1]?.init.method).toBe("POST");
    expect(calls[1]?.init.body).toBe(JSON.stringify({ confirm_token: "tok-1" }));
  });

  it("maps error bodies to EngineError kinds", async () => {
    const { fn } = fakeFetch(() => ({ status: 429, body: { error: { kind: "usage_limit", message: "limit" } } }));
    const api = new HttpEngineApi({ baseUrl: "http://x", token: "t" }, fn);
    await expect(api.translate(1, "t")).rejects.toMatchObject({ kind: "usage_limit", status: 429 });
  });

  it("reports network failures as unavailable", async () => {
    const fn = (async () => {
      throw new TypeError("connection refused");
    }) as typeof fetch;
    const api = new HttpEngineApi({ baseUrl: "http://x", token: "t" }, fn);
    const err = await api.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EngineError);
    expect((err as EngineError).kind).toBe("unavailable");
  });

  it("builds asset URLs with the token", () => {
    const api = new HttpEngineApi({ baseUrl: "http://127.0.0.1:1", token: "t" }, (async () => new Response()) as typeof fetch);
    expect(api.assetUrl(2, "p001_b0.png")).toBe("http://127.0.0.1:1/api/books/2/assets/p001_b0.png?token=t");
  });
});
