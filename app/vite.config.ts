/// <reference types="vitest/config" />
import { cpSync, existsSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const root = dirname(fileURLToPath(import.meta.url));

/**
 * PDF.js data files (CMaps for CJK/non-embedded fonts, standard fonts, ICC profiles, image-decoder wasm)
 * are copied into public/pdfjs (gitignored) so dev and build serve them from 'self'.
 * quickjs-eval.wasm (PDF JavaScript) is deliberately left out: scripting stays off.
 */
function pdfjsAssets(): Plugin {
  return {
    name: "rosetta-pdfjs-assets",
    buildStart() {
      const src = join(root, "node_modules", "pdfjs-dist");
      const dest = join(root, "public", "pdfjs");
      if (!existsSync(src)) return;
      mkdirSync(join(dest, "wasm"), { recursive: true });
      cpSync(join(src, "cmaps"), join(dest, "cmaps"), { recursive: true });
      cpSync(join(src, "standard_fonts"), join(dest, "standard_fonts"), { recursive: true });
      cpSync(join(src, "iccs"), join(dest, "iccs"), { recursive: true });
      for (const f of readdirSync(join(src, "wasm"))) {
        if (f.endsWith(".wasm") && !f.startsWith("quickjs")) cpSync(join(src, "wasm", f), join(dest, "wasm", f));
      }
    },
  };
}

const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react(), pdfjsAssets()],
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    watch: { ignored: ["**/src-tauri/**"] },
  },
  envPrefix: ["VITE_", "TAURI_ENV_", "ROSETTA_"],
  build: {
    target: "es2022",
    sourcemap: !!process.env.TAURI_ENV_DEBUG,
    chunkSizeWarningLimit: 1500,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["src/test/setup.ts"],
    css: false,
  },
});
