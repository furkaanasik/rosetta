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

  it("maps a 409 conflict (book file changed) to its own kind", async () => {
    const fn = (async () =>
      new Response(JSON.stringify({ error: { kind: "conflict", message: "Dosya değişmiş" } }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      })) as unknown as typeof fetch;
    const api = new HttpEngineApi({ baseUrl: "http://x", token: "t" }, fn);
    await expect(api.getBook(1)).rejects.toMatchObject({ kind: "conflict", status: 409 });
  });

  it("reports network failures as offline (engine down)", async () => {
    const fn = (async () => {
      throw new TypeError("connection refused");
    }) as typeof fetch;
    const api = new HttpEngineApi({ baseUrl: "http://x", token: "t" }, fn);
    const err = await api.health().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(EngineError);
    expect((err as EngineError).kind).toBe("offline");
  });

  it("fetches assets with the bearer header, never a token in the URL", async () => {
    const seen: { url: string; auth: string | null }[] = [];
    const fn = (async (url: string, init?: RequestInit) => {
      seen.push({ url, auth: new Headers(init?.headers).get("Authorization") });
      return new Response(new Uint8Array([1, 2]), { headers: { "Content-Type": "image/png" } });
    }) as unknown as typeof fetch;
    const api = new HttpEngineApi({ baseUrl: "http://127.0.0.1:1", token: "t" }, fn);
    const blob = await api.assetBlob(2, "p001_b0.png");
    expect(blob.size).toBe(2);
    expect(seen[0]).toEqual({ url: "http://127.0.0.1:1/api/books/2/assets/p001_b0.png", auth: "Bearer t" });
  });
});
