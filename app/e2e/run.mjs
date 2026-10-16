#!/usr/bin/env node
/**
 * E2E runner: starts a throwaway engine (`rosetta serve --dev-fake-ai`, so no AI call can ever
 * leave the machine) and Vite, then runs Playwright against them.
 *
 *   npm run e2e            synthetic test book, fake provider
 *   npm run e2e -- --ddia  read-only visual check of the DDIA book on a COPY of the user's data
 *
 * The engine never sees the real data dir: everything lives in a temp dir that is removed after.
 */
import { spawn, execFileSync } from "node:child_process";
import { cpSync, existsSync, mkdtempSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { delimiter, dirname, join, resolve } from "node:path";
import { createConnection } from "node:net";
import { createInterface } from "node:readline";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const appDir = resolve(here, "..");
const engineDir = resolve(appDir, "..", "engine");
const ddia = process.argv.includes("--ddia");
const passThrough = process.argv.slice(2).filter((a) => a !== "--ddia");

const DDIA_PDF = join(homedir(), "SSD/Books/Designing Data-Intensive Applications 2nd.pdf");
const REAL_DATA = join(homedir(), ".local/share/rosetta");

const work = mkdtempSync(join(tmpdir(), "rosetta-e2e-"));
const dataDir = join(work, "data");
const cfgDir = join(work, "cfg");
execFileSync("mkdir", ["-p", dataDir, cfgDir]);

let bookPath;
if (ddia) {
  if (!existsSync(DDIA_PDF)) {
    console.log("DDIA PDF bulunamadı; atlanıyor.");
    process.exit(0);
  }
  // Copy (never touch) the user's DB and outputs; display the Sonnet translations.
  cpSync(join(REAL_DATA, "rosetta.db"), join(dataDir, "rosetta.db"));
  if (existsSync(join(REAL_DATA, "out"))) cpSync(join(REAL_DATA, "out"), join(dataDir, "out"), { recursive: true });
  writeFileSync(join(cfgDir, "config.toml"), 'provider = "claude-cli"\nmodel = "sonnet"\n');
  bookPath = DDIA_PDF;
} else {
  // One page per batch so a job can be paused between pages.
  writeFileSync(join(cfgDir, "config.toml"), 'provider = "fake"\nmodel = "fake"\nbatch_max_pages = 1\n');
  bookPath = join(work, "book.pdf");
  execFileSync("uv", ["run", "python", join(here, "make_book.py"), bookPath], { cwd: engineDir, stdio: "inherit" });
}
// The dictionary is read-only (opened with mode=ro); link it instead of copying 150 MB.
const dict = join(REAL_DATA, "dictionary.db");
if (existsSync(dict)) symlinkSync(dict, join(dataDir, "dictionary.db"));

// Belt and braces: the engine's PATH has no `claude` binary at all.
const uv = execFileSync("sh", ["-c", "command -v uv"]).toString().trim();
const claudeDir = (() => {
  try {
    return dirname(execFileSync("sh", ["-c", "command -v claude"]).toString().trim());
  } catch {
    return null;
  }
})();
const enginePath = (process.env.PATH ?? "")
  .split(delimiter)
  .filter((d) => d && d !== claudeDir)
  .join(delimiter);

const token = randomBytes(16).toString("hex");
const children = [];
const cleanup = () => {
  for (const c of children) if (c.exitCode === null) c.kill("SIGTERM");
  rmSync(work, { recursive: true, force: true });
};
process.on("SIGINT", () => {
  cleanup();
  process.exit(130);
});

// Like the desktop app: token via the environment (not argv), stdin kept open as a pipe so the
// engine exits by itself when this runner goes away.
const engine = spawn(uv, ["run", "rosetta", "serve", "--port", "0", "--dev-fake-ai", "--dev-fake-delay", ddia ? "0" : "1"], {
  cwd: engineDir,
  env: { ...process.env, PATH: enginePath, ROSETTA_DATA_DIR: dataDir, ROSETTA_CONFIG_DIR: cfgDir, ROSETTA_SERVE_TOKEN: token, ROSETTA_CLAUDE_AUTODETECT: "0" },
  stdio: ["pipe", "pipe", "inherit"],
});
children.push(engine);
const port = await new Promise((ok, fail) => {
  const rl = createInterface({ input: engine.stdout });
  rl.once("line", (line) => ok(JSON.parse(line).port));
  engine.once("exit", (code) => fail(new Error(`engine exited ${code}`)));
});
const engineUrl = `http://127.0.0.1:${port}`;
console.log(`motor: ${engineUrl}`);

// Port 1420 is fixed (the engine's CORS allowlist). If another E2E run holds it, our Vite fails to
// bind and the tests would silently drive *that* run's frontend + engine — wait for it instead.
const listening = (host) =>
  new Promise((ok) => {
    const sock = createConnection({ host, port: 1420 });
    sock.once("connect", () => (sock.destroy(), ok(true)));
    sock.once("error", () => ok(false));
  });
// Vite may bind IPv4 or IPv6 "localhost"; a second Vite can take the other family unnoticed.
const portBusy = async () => (await listening("127.0.0.1")) || (await listening("::1"));
for (let waited = 0; await portBusy(); waited += 2) {
  if (waited === 0) console.log("port 1420 dolu (başka bir E2E çalışıyor?) — bekleniyor…");
  if (waited > 900) throw new Error("port 1420 15 dakikadır dolu");
  await new Promise((r) => setTimeout(r, 2000));
}

const vite = spawn("npx", ["vite", "--port", "1420", "--strictPort"], {
  cwd: appDir,
  env: { ...process.env, VITE_ENGINE_URL: engineUrl, VITE_ENGINE_TOKEN: token },
  stdio: ["ignore", "ignore", "inherit"],
});
children.push(vite);
let viteExited = null;
vite.once("exit", (code) => (viteExited = code));
for (let i = 0; ; i++) {
  if (viteExited !== null) throw new Error(`vite exited (${viteExited}); port 1420 taken?`);
  try {
    if ((await fetch("http://localhost:1420/")).ok) break;
  } catch {
    /* not up yet */
  }
  if (i > 100) throw new Error("vite did not start");
  await new Promise((r) => setTimeout(r, 200));
}

const specs = ddia ? ["e2e/ddia.spec.ts"] : ["--grep-invert", "@ddia"];
const pw = spawn("npx", ["playwright", "test", "-c", "e2e/playwright.config.ts", ...specs, ...passThrough], {
  cwd: appDir,
  env: { ...process.env, E2E_BOOK: bookPath, E2E_ENGINE_URL: engineUrl, E2E_TOKEN: token, E2E_DDIA: ddia ? "1" : "" },
  stdio: "inherit",
});
const code = await new Promise((r) => pw.once("exit", r));
cleanup();
process.exit(code ?? 1);
