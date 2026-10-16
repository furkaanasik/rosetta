import type { EngineApi } from "../api/engine";
import { HttpEngineApi } from "../api/http";
import { MockEngineApi } from "../api/mock";
import type { EngineInfo } from "../api/types";

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

/**
 * Resolve the engine connection:
 * 1. Tauri: ask the Rust side (`engine_info`), which spawned the sidecar or read
 *    ROSETTA_ENGINE_URL / ROSETTA_ENGINE_TOKEN in dev.
 * 2. Browser dev (`npm run dev`): VITE_ENGINE_URL/VITE_ENGINE_TOKEN, else the mock.
 */
export async function connectEngine(): Promise<{ api: EngineApi; mock: boolean }> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const { listen } = await import("@tauri-apps/api/event");
    // The first start of the packaged engine unpacks itself and can take a while: wait up to
    // ~30 s, but stop early as soon as Rust reports the engine ready or failed.
    let wake: () => void = () => undefined;
    const woken = new Promise<void>((r) => (wake = r));
    const unlisten = await Promise.all([listen("engine-ready", () => wake()), listen("engine-error", () => wake())]);
    try {
      const info = await waitForEngine(() => invoke<EngineInfo | null>("engine_info"), 150, 200, woken);
      if (info) return { api: new HttpEngineApi(info), mock: false };
      throw new Error("Motor 30 saniyede başlamadı");
    } finally {
      unlisten.forEach((u) => u());
    }
  }
  const url = import.meta.env.VITE_ENGINE_URL as string | undefined;
  const token = import.meta.env.VITE_ENGINE_TOKEN as string | undefined;
  if (url) return { api: new HttpEngineApi({ baseUrl: url, token: token ?? "" }), mock: false };
  return { api: new MockEngineApi({ latencyMs: 120 }), mock: true };
}

/**
 * Polls `probe` (which rejects with the engine's error) until it yields an address. `wake`
 * (engine ready/failed) cuts the current wait short so the next probe answers at once.
 */
export async function waitForEngine(
  probe: () => Promise<EngineInfo | null>,
  tries = 150,
  intervalMs = 200,
  wake: Promise<void> = new Promise(() => undefined),
): Promise<EngineInfo | null> {
  for (let i = 0; i < tries; i++) {
    const info = await probe();
    if (info) return info;
    await Promise.race([new Promise((r) => setTimeout(r, intervalMs)), wake]);
  }
  return null;
}

/** Open-file dialog (Tauri) or a prompt fallback in the browser. */
export async function pickPdf(): Promise<string | null> {
  if (isTauri()) {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const res = await open({ multiple: false, filters: [{ name: "PDF", extensions: ["pdf"] }] });
    return typeof res === "string" ? res : null;
  }
  return window.prompt("PDF yolu:", "/home/user/kitap.pdf");
}

/** URL the PDF.js viewer can load for a local file. */
export async function pdfSource(path: string): Promise<string | null> {
  if (isTauri()) {
    const { convertFileSrc } = await import("@tauri-apps/api/core");
    return convertFileSrc(path);
  }
  return null;
}

/**
 * PDF given at launch: argv / "Open with Rosetta" in Tauri (taken once), or `?open=<path>`
 * in browser dev.
 */
export async function initialPdf(search: string = typeof window !== "undefined" ? window.location.search : ""): Promise<string | null> {
  if (isTauri()) {
    const { invoke } = await import("@tauri-apps/api/core");
    return (await invoke<string | null>("initial_pdf")) ?? null;
  }
  const path = new URLSearchParams(search).get("open");
  return path && path.trim() ? path : null;
}

/**
 * A second launch ("Open with Rosetta" while running) stored a PDF for us (Tauri only). The
 * event is only a signal: the path is drained with `initialPdf()`, so a hand-over that
 * happened before this listener existed is picked up by the startup drain instead.
 */
export async function onOpenPdf(cb: () => void): Promise<() => void> {
  if (!isTauri()) return () => undefined;
  const { listen } = await import("@tauri-apps/api/event");
  return listen("open-pdf", () => cb());
}

/** Engine failures after startup (crash, exit), as reported by the Rust side (Tauri only). */
export async function onEngineError(cb: (message: string) => void): Promise<() => void> {
  if (!isTauri()) return () => undefined;
  const { listen } = await import("@tauri-apps/api/event");
  return listen<string>("engine-error", (e) => cb(e.payload));
}
