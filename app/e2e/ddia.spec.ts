import { expect, test } from "@playwright/test";

/**
 * @ddia — read-only visual check of the DDIA book (run: `npm run e2e:ddia`). The engine runs on a
 * COPY of the user's data with `--dev-fake-ai`: the stored Sonnet translations are displayed, and
 * the dev translator refuses to translate for the real provider, so no AI call is possible.
 */
const BOOK = process.env.E2E_BOOK ?? "";
const SHOTS = "e2e/screenshots";
const PAGES = [25, 30, 59, 94, 115];

test.skip(!process.env.E2E_DDIA, "run with npm run e2e:ddia");

test("DDIA: Split and Sadece Çeviri on the translated pages @ddia", async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.goto("/");
  page.once("dialog", (d) => void d.accept(BOOK));
  await page.getByRole("button", { name: "PDF Aç" }).click();
  await expect(page.locator(".topbar .title")).toContainText("Designing Data-Intensive");
  const before = (await page.getByTestId("spend").textContent()) ?? "";

  for (const n of PAGES) {
    await page.getByLabel("Sayfa numarası").fill(String(n));
    await page.getByRole("tablist", { name: "Görünüm modu" }).getByRole("tab", { name: "Split" }).click();
    const right = page.locator(".split .html-pane .engine-html");
    // Real Sonnet translations are shown (Turkish text, no "not translated yet" banner).
    await expect(right).toContainText(/[çğıöşüÇĞİÖŞÜ]/, { timeout: 20_000 });
    await expect(page.getByText("Bu sayfa henüz çevrilmedi")).toBeHidden();
    await expect(page.getByLabel(`PDF sayfa ${n}`)).toBeVisible();
    await page.waitForTimeout(600); // let PDF.js finish painting
    await page.screenshot({ path: `${SHOTS}/ddia-p${n}-split.png` });

    await page.getByRole("tablist", { name: "Görünüm modu" }).getByRole("tab", { name: "Sadece Çeviri" }).click();
    await expect(page.locator(".html-pane .engine-html")).toContainText(/[çğıöşü]/);
    await page.screenshot({ path: `${SHOTS}/ddia-p${n}-ceviri.png` });
  }

  // Nothing above may have cost anything.
  expect((await page.getByTestId("spend").textContent()) ?? "").toBe(before);
});
