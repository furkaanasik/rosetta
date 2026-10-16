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
    const info = await waitForEngine(() => invoke<EngineInfo | null>("engine_info"));
    if (info) return { api: new HttpEngineApi(info), mock: false };
    throw new Error("Motor başlatılamadı");
  }
  const url = import.meta.env.VITE_ENGINE_URL as string | undefined;
  const token = import.meta.env.VITE_ENGINE_TOKEN as string | undefined;
  if (url) return { api: new HttpEngineApi({ baseUrl: url, token: token ?? "" }), mock: false };
  return { api: new MockEngineApi({ latencyMs: 120 }), mock: true };
}

async function waitForEngine(
  probe: () => Promise<EngineInfo | null>,
  tries = 50,
  intervalMs = 200,
): Promise<EngineInfo | null> {
  for (let i = 0; i < tries; i++) {
    const info = await probe();
    if (info) return info;
    await new Promise((r) => setTimeout(r, intervalMs));
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
