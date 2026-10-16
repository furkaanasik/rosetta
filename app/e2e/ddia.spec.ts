import { expect, test, type Page } from "@playwright/test";

/**
 * @ddia — read-only visual check of the DDIA book (run: `npm run e2e:ddia`). The engine runs on a
 * COPY of the user's data with `--dev-fake-ai`: the stored Sonnet translations are displayed, and
 * the dev translator refuses to translate for the real provider, so no AI call is possible.
 */
const BOOK = process.env.E2E_BOOK ?? "";
const SHOTS = "e2e/screenshots";
const PAGES = [25, 30, 59, 94, 115];

const sheet = (p: Page, n: number, kind: "orijinal" | "Türkçe") => p.getByRole("figure", { name: `Sayfa ${n} (${kind})`, exact: true });

/** All book sheets of a page (the page itself and its "devam" continuations). */
const bookSheets = (p: Page, n: number) => p.getByRole("figure", { name: new RegExp(`^Sayfa ${n} \\(Türkçe\\)`) });

/** Figure/table crops are fetched with the bearer token (blob URLs): wait until all are painted. */
async function figuresLoaded(p: Page, n: number) {
  const html = bookSheets(p, n).locator(".engine-html");
  await expect
    .poll(() =>
      html.evaluateAll((roots) =>
        roots.every((root) =>
          Array.from(root.querySelectorAll<HTMLImageElement>("img")).every((img) => img.complete && img.naturalWidth > 0),
        ),
      ),
    )
    .toBe(true);
  const srcs = await html.locator("img").evaluateAll((els) => els.map((e) => e.getAttribute("src") ?? ""));
  expect(srcs.every((s) => s.startsWith("blob:") && !s.includes("token"))).toBe(true);
}

async function gotoPage(p: Page, n: number) {
  const field = p.getByLabel("Sayfa numarası");
  await field.fill(String(n));
  await field.press("Enter");
  await expect(field).toHaveValue(String(n));
}

async function mode(p: Page, label: "Yan yana" | "Türkçe" | "Orijinal") {
  await p.getByRole("tablist", { name: "Görünüm modu" }).getByRole("tab", { name: label }).click();
}

test.skip(!process.env.E2E_DDIA, "run with npm run e2e:ddia");

for (const [scheme, w, h] of [
  ["light", 1600, 1000],
  ["light", 1280, 800],
  ["dark", 1280, 800],
  ["dark", 1920, 1080],
] as const) {
  test(`DDIA: Yan yana and Türkçe on the translated pages (${scheme} ${w}×${h}) @ddia`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
    await page.setViewportSize({ width: w, height: h });
    await page.goto("/");
    page.once("dialog", (d) => void d.accept(BOOK));
    await page.getByRole("button", { name: "PDF aç" }).click();
    await expect(page.locator(".topbar .title")).toContainText("Designing Data-Intensive");
    const before = (await page.getByTestId("spend").textContent()) ?? "";
    const tag = `${scheme}-${w}x${h}`;
    if (scheme === "light" && w === 1600) {
      await page.getByRole("button", { name: "Kitaplık" }).click();
      const shelf = page.getByRole("region", { name: "Son açılanlar" });
      await expect(shelf.getByRole("button").first()).toBeVisible();
      await page.waitForTimeout(800); // cover thumbnails
      await page.screenshot({ path: `${SHOTS}/v2/ddia-${tag}-library.png` });
      await shelf.getByRole("button", { name: /Designing Data-Intensive/ }).first().click();
    }

    for (const n of PAGES) {
      await mode(page, "Yan yana");
      await gotoPage(page, n);
      const tr = sheet(page, n, "Türkçe");
      // Real Sonnet translations are shown (Turkish text, no "not translated yet" card).
      await expect(tr.locator(".engine-html")).toContainText(/[çğıöşüÇĞİÖŞÜ]/, { timeout: 20_000 });
      await expect(tr.getByText("Bu sayfa henüz çevrilmedi")).toBeHidden();
      await expect(page.getByLabel(`PDF sayfa ${n}`)).toBeVisible();
      await figuresLoaded(page, n);
      await page.waitForTimeout(700); // let PDF.js finish painting
      await page.screenshot({ path: `${SHOTS}/v2/ddia-${tag}-p${n}-yan-yana.png` });

      await mode(page, "Türkçe");
      await expect(sheet(page, n, "Türkçe").locator(".engine-html")).toContainText(/[çğıöşü]/);
      await figuresLoaded(page, n);
      await page.screenshot({ path: `${SHOTS}/v2/ddia-${tag}-p${n}-turkce.png` });
      // Book pages: text that doesn't fit continues on a "devam" sheet of the same size.
      const cont = page.getByRole("figure", { name: `Sayfa ${n} (Türkçe), devam 1`, exact: true });
      if (await cont.count()) {
        await cont.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await page.waitForTimeout(300);
        await page.screenshot({ path: `${SHOTS}/v2/ddia-${tag}-p${n}-turkce-devam.png` });
      }
    }

    // Nothing above may have cost anything.
    expect((await page.getByTestId("spend").textContent()) ?? "").toBe(before);
  });
}
