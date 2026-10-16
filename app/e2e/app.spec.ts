import { expect, test, type Page } from "@playwright/test";

/**
 * Full user flows against a live engine started by e2e/run.mjs with `--dev-fake-ai`
 * (fake translator + fake profile/explain; no AI call can leave the machine).
 * One page is shared across the steps, like a real session.
 */
const BOOK = process.env.E2E_BOOK ?? "";
const SHOTS = "e2e/screenshots";

test.describe.configure({ mode: "serial" });

let page: Page;

async function spend(p: Page): Promise<string> {
  return (await p.getByTestId("spend").textContent()) ?? "";
}

async function confirmCost(p: Page): Promise<void> {
  const modal = p.getByRole("dialog", { name: /maliyet onayı/ });
  await expect(modal).toBeVisible();
  await modal.getByRole("button", { name: "Onayla" }).click();
  await expect(modal).toBeHidden({ timeout: 30_000 });
}

async function mode(p: Page, label: "Orijinal" | "Yan yana" | "Türkçe" | "Öğrenme"): Promise<void> {
  await p.getByRole("tablist", { name: "Görünüm modu" }).getByRole("tab", { name: label }).click();
}

/** Opens the side panel on a tab. */
async function panel(p: Page, label: "İçindekiler" | "İşler" | "Kelimeler" | "Profil"): Promise<void> {
  const side = p.locator("aside.side-panel");
  if ((await side.getAttribute("data-open")) !== "true") await p.getByRole("button", { name: "Yan panel" }).click();
  await side.getByRole("tablist", { name: "Paneller" }).getByRole("tab", { name: label }).click();
}

async function closePanel(p: Page): Promise<void> {
  const side = p.locator("aside.side-panel");
  if ((await side.getAttribute("data-open")) === "true") await side.getByRole("button", { name: "Paneli kapat" }).click();
}

/** "Çevir ▾" menu item. */
async function translateMenu(p: Page, item: string): Promise<void> {
  await p.getByRole("button", { name: "Diğer çeviri seçenekleri" }).click();
  await p.getByRole("menuitem", { name: item }).click();
}

const sheet = (p: Page, n: number, kind: "orijinal" | "Türkçe" | "öğrenme") => p.getByRole("figure", { name: `Sayfa ${n} (${kind})` });
const toasts = (p: Page) => p.locator(".toasts");

test.beforeAll(async ({ browser }) => {
  expect(BOOK, "E2E_BOOK must be set (run via npm run e2e)").not.toBe("");
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
});

test.afterAll(async () => {
  await page.close();
});

test("library → open a PDF → reader", async () => {
  await page.goto("/");
  await expect(page.getByText("Motor bağlı", { exact: true })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/v2/light-1440x900-library-empty.png` });
  page.once("dialog", (d) => void d.accept(BOOK));
  await page.getByRole("button", { name: "PDF aç" }).click();
  await expect(page.locator(".topbar .title")).toHaveText("book");
  await expect(page.getByRole("navigation", { name: "Sayfa" })).toContainText("/ 4");
  // TOC from the PDF outline, in the side panel.
  await panel(page, "İçindekiler");
  await expect(page.getByText("Chapter 5. Replication").first()).toBeVisible();
  await closePanel(page);
});

test("Orijinal mode renders the PDF page as a sheet", async () => {
  await mode(page, "Orijinal");
  const canvas = page.getByLabel("PDF sayfa 1");
  await expect(canvas).toBeVisible();
  await expect.poll(async () => (await canvas.boundingBox())?.height ?? 0).toBeGreaterThan(300);
  await page.screenshot({ path: `${SHOTS}/01-orijinal.png` });
});

test("translate page: cancel makes no call, confirm translates", async () => {
  await mode(page, "Türkçe");
  await expect(sheet(page, 1, "Türkçe").getByText("Bu sayfa henüz çevrilmedi")).toBeVisible();
  const before = await spend(page);

  const primary = page.getByRole("button", { name: /Bu sayfayı çevir \(sayfa/ });
  await primary.click();
  const modal = page.getByRole("dialog", { name: /maliyet onayı/ });
  await expect(modal).toBeVisible();
  await expect(modal.getByTestId("cost-calls")).toHaveText("1");
  await modal.getByRole("button", { name: "İptal" }).click();
  await expect(modal).toBeHidden();
  await page.waitForTimeout(500);
  expect(await spend(page)).toBe(before);
  await expect(sheet(page, 1, "Türkçe").getByText("Bu sayfa henüz çevrilmedi")).toBeVisible();

  await primary.click();
  await confirmCost(page);
  await expect(sheet(page, 1, "Türkçe").locator(".engine-html")).toContainText("[TR] Replication means");
  await expect(page.getByTestId("spend")).toContainText("1 çağrı");
  await page.screenshot({ path: `${SHOTS}/02-turkce.png` });
});

test("Yan yana: pages line up, block click highlights both sides", async () => {
  await mode(page, "Yan yana");
  const right = sheet(page, 1, "Türkçe");
  await expect(right.locator(".engine-html")).toContainText("[TR]");
  const sentence = right.locator('[data-block="0-2"] [data-s="1"]');
  await sentence.click();
  await expect(page.getByTestId("pdf-highlight")).toBeVisible();
  await expect.poll(() => sentence.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");

  // Original and Turkish sheets of a page share a row: same top edge.
  const [a, b] = await Promise.all([sheet(page, 1, "orijinal").boundingBox(), right.boundingBox()]);
  expect(Math.abs((a?.y ?? 0) - (b?.y ?? 99))).toBeLessThanOrEqual(2);
  await page.screenshot({ path: `${SHOTS}/03-yan-yana.png` });
});

test("range job: progress, pause, resume, retry failed pages", async () => {
  await translateMenu(page, "Aralık çevir…");
  await page.getByPlaceholder("ör. 120-140").fill("2-4");
  await page.getByRole("button", { name: "Aralığı çevir" }).click();
  await confirmCost(page);

  // Starting a job opens the side panel on İşler.
  const job = page.locator("article.job").first();
  await expect(job).toContainText("Çalışıyor");
  await job.getByRole("button", { name: "Duraklat" }).click();
  await expect(job).toContainText("Duraklatıldı", { timeout: 15_000 });
  await expect(job).toContainText("Duraklatma istendi.");
  await page.screenshot({ path: `${SHOTS}/04-is-duraklatildi.png` });

  await job.getByRole("button", { name: "Devam" }).click();
  await confirmCost(page);
  // Page 3 carries the dev marker → one simulated provider error → a failed page.
  await expect(job.getByText(/1 hatalı sayfa/)).toBeVisible({ timeout: 30_000 });
  await expect(job).not.toContainText("Çalışıyor", { timeout: 30_000 });

  await job.getByRole("button", { name: "Sadece hatalıları tekrar dene" }).click();
  await confirmCost(page);
  await expect(job.getByText(/hatalı sayfa/)).toBeHidden({ timeout: 30_000 });
  await expect(job).toContainText("3/3 sayfa");
  await page.screenshot({ path: `${SHOTS}/05-isler.png` });
});

test("Tüm kitabı çevir: everything cached → no AI call needed", async () => {
  await translateMenu(page, "Tüm kitabı çevir…");
  await page.getByRole("button", { name: "Tümünü çevir" }).click();
  const modal = page.getByRole("dialog", { name: /maliyet onayı/ });
  await expect(modal.getByTestId("cost-calls")).toHaveText("0");
  await expect(modal).toContainText("Tümü önbellekte");
  await confirmCost(page);
  await expect(page.locator("article.job").first()).toContainText("Bitti", { timeout: 30_000 });
});

test("Kitabı analiz et → profile editor shows the result and saves edits", async () => {
  await translateMenu(page, "Kitabı analiz et…");
  await confirmCost(page);
  const editor = page.getByRole("region", { name: "Kitap profili" });
  await expect(editor.getByLabel("Tür")).toHaveValue("yazılım / veri sistemleri");
  await expect(editor.getByLabel("Terim", { exact: true }).first()).toHaveValue("replication");

  await editor.getByRole("button", { name: "Terim ekle" }).click();
  await editor.getByLabel("Terim", { exact: true }).last().fill("leader");
  await editor.getByLabel("Karşılık", { exact: true }).last().fill("lider");
  await editor.getByLabel("Yeni çevrilmeyecek terim").fill("Kafka");
  await editor.getByLabel("Yeni çevrilmeyecek terim").press("Enter");
  await editor.getByRole("button", { name: "Kaydet" }).click();
  await expect(toasts(page)).toContainText("Profil kaydedildi");

  await panel(page, "İçindekiler");
  await panel(page, "Profil");
  await expect(editor.getByLabel("Terim", { exact: true }).last()).toHaveValue("leader");
  await expect(editor.locator(".chip", { hasText: "Kafka" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-profil.png` });
  await closePanel(page);
});

test("PDF olarak dışa aktar produces a file without AI", async () => {
  const before = await spend(page);
  await translateMenu(page, "PDF olarak dışa aktar — Türkçe");
  await expect(toasts(page)).toContainText("PDF hazır", { timeout: 60_000 });
  expect(await spend(page)).toBe(before);
});

test("Öğrenme: click word → lookup → save unknown → ruby appears", async () => {
  await mode(page, "Öğrenme");
  const pane = sheet(page, 1, "öğrenme");
  const word = pane.locator('[data-block="0-2"] [data-w="replication"]').first();
  await expect(word).toBeVisible();
  await word.click();
  const pop = page.getByRole("dialog", { name: "Sözlük: replication" });
  await expect(pop).toBeVisible();
  await expect(pop.locator(".tr")).toContainText("replikasyon");
  await pop.getByRole("button", { name: "Kaydet (bilmiyorum)" }).click();
  await expect(pop.getByRole("button", { name: "Kaydedildi" })).toBeVisible();
  await pop.getByRole("button", { name: "Kapat" }).click();
  await expect(pane.locator("ruby rt").first()).toHaveText("replikasyon");
  await page.screenshot({ path: `${SHOTS}/07-ogrenme.png` });
});

test("flashcard review and stats", async () => {
  await panel(page, "Kelimeler");
  const learn = page.getByRole("region", { name: "Öğrenme" });
  await expect(learn.locator("ul.vocab")).toContainText("replication");
  await learn.getByRole("tab", { name: "Tekrar" }).click();
  await expect(learn.locator(".cloze")).toContainText("_____");
  await learn.getByRole("button", { name: "Cevabı göster" }).click();
  await learn.getByRole("button", { name: "İyi" }).click();
  await learn.getByRole("tab", { name: "İstatistik" }).click();
  const stats = learn.locator("dl.stats");
  await expect(stats).toContainText("Bugün yapılan");
  await expect(stats.locator("dd").nth(3)).toHaveText("1");
  await page.screenshot({ path: `${SHOTS}/08-istatistik.png` });
  await closePanel(page);
});

test("Bunu açıkla: cost confirm first time, cached second time", async () => {
  const pane = sheet(page, 1, "öğrenme");
  await pane.locator('[data-block="0-2"] [data-w="replication"]').first().click();
  const pop = page.getByRole("dialog", { name: "Sözlük: replication" });
  await pop.getByRole("button", { name: "Bunu açıkla…" }).click();
  await confirmCost(page);
  const box = page.getByRole("dialog", { name: "Açıklama" });
  await expect(box).toContainText("Sahte açıklama");
  await expect(box.locator("strong", { hasText: "Yapı:" })).toBeVisible();
  await expect(box).not.toContainText("**");
  await page.screenshot({ path: `${SHOTS}/09-aciklama.png` });
  await box.getByRole("button", { name: "Kapat", exact: true }).click();

  await pane.locator('[data-block="0-2"] [data-w="replication"]').first().click();
  await page.getByRole("dialog", { name: "Sözlük: replication" }).getByRole("button", { name: "Bunu açıkla…" }).click();
  await expect(page.getByRole("dialog", { name: /maliyet onayı/ })).toBeHidden();
  await expect(page.getByRole("dialog", { name: "Açıklama" })).toContainText("önbellekten");
  await page.getByRole("dialog", { name: "Açıklama" }).getByRole("button", { name: "Kapat", exact: true }).click();
});

/** Design review matrix: light/dark × two window sizes (docs/ui-redesign.md acceptance 1). */
for (const scheme of ["light", "dark"] as const) {
  for (const [w, h] of [
    [1280, 800],
    [1920, 1080],
  ] as const) {
    test(`screens: ${scheme} ${w}×${h}`, async () => {
      const shot = (name: string) => page.screenshot({ path: `${SHOTS}/v2/${scheme}-${w}x${h}-${name}.png` });
      await page.emulateMedia({ colorScheme: scheme, reducedMotion: "reduce" });
      await page.setViewportSize({ width: w, height: h });
      const before = await spend(page);

      await page.getByRole("button", { name: "Kitaplık" }).click();
      const card = page.getByRole("region", { name: "Son açılanlar" }).getByRole("button").first();
      await expect(card).toBeVisible();
      await shot("library");
      await card.click();
      await expect(page.locator(".topbar .title")).toHaveText("book");

      for (const [label, file] of [
        ["Orijinal", "mode-orijinal"],
        ["Yan yana", "mode-yan-yana"],
        ["Türkçe", "mode-turkce"],
        ["Öğrenme", "mode-ogrenme"],
      ] as const) {
        await mode(page, label);
        await page.waitForTimeout(700); // PDF.js paint + HTML fetch
        await shot(file);
      }

      for (const [tab, file] of [
        ["İçindekiler", "panel-icindekiler"],
        ["İşler", "panel-isler"],
        ["Kelimeler", "panel-kelimeler"],
        ["Profil", "panel-profil"],
      ] as const) {
        await panel(page, tab);
        await page.waitForTimeout(250);
        await shot(file);
      }
      await closePanel(page);

      await page.keyboard.press("Control+k");
      const palette = page.getByRole("dialog", { name: "Komut paleti" });
      await expect(palette).toBeVisible();
      await shot("palette");
      await page.keyboard.press("Escape");
      await expect(palette).toBeHidden();

      await translateMenu(page, "Bu sayfayı yeniden çevir…");
      const modal = page.getByRole("dialog", { name: /maliyet onayı/ });
      await expect(modal).toBeVisible();
      await shot("cost-modal");
      await modal.getByRole("button", { name: "İptal" }).click();
      await expect(modal).toBeHidden();

      // Looking around never costs anything.
      expect(await spend(page)).toBe(before);
    });
  }
}
