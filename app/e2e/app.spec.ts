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

async function mode(p: Page, label: string): Promise<void> {
  await p.getByRole("tablist", { name: "Görünüm modu" }).getByRole("tab", { name: label }).click();
}

async function panel(p: Page, label: string): Promise<void> {
  await p.getByRole("tablist", { name: "Paneller" }).getByRole("tab", { name: label }).click();
}

test.beforeAll(async ({ browser }) => {
  expect(BOOK, "E2E_BOOK must be set (run via npm run e2e)").not.toBe("");
  page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
});

test.afterAll(async () => {
  await page.close();
});

test("connects to the live engine and opens a PDF", async () => {
  await page.goto("/");
  await expect(page.getByText("Motor bağlı", { exact: true })).toBeVisible();
  page.once("dialog", (d) => void d.accept(BOOK));
  await page.getByRole("button", { name: "PDF Aç" }).click();
  await expect(page.locator(".topbar .title")).toHaveText("book");
  await expect(page.getByRole("navigation", { name: "Sayfa" })).toContainText("/ 4");
  // TOC from the PDF outline.
  await expect(page.getByText("Chapter 5. Replication").first()).toBeVisible();
});

test("Orijinal mode renders the PDF page", async () => {
  await mode(page, "Orijinal");
  const canvas = page.getByLabel("PDF sayfa 1");
  await expect(canvas).toBeVisible();
  await expect.poll(async () => (await canvas.boundingBox())?.height ?? 0).toBeGreaterThan(300);
  await page.screenshot({ path: `${SHOTS}/01-orijinal.png` });
});

test("translate page: cancel makes no call, confirm translates", async () => {
  await mode(page, "Sadece Çeviri");
  await expect(page.getByText("Bu sayfa henüz çevrilmedi")).toBeVisible();
  const before = await spend(page);

  await page.getByRole("button", { name: /Bu Sayfayı Çevir/ }).click();
  const modal = page.getByRole("dialog", { name: /maliyet onayı/ });
  await expect(modal).toBeVisible();
  await expect(modal.getByTestId("cost-calls")).toHaveText("1");
  await modal.getByRole("button", { name: "İptal" }).click();
  await expect(modal).toBeHidden();
  await page.waitForTimeout(500);
  expect(await spend(page)).toBe(before);
  await expect(page.getByText("Bu sayfa henüz çevrilmedi")).toBeVisible();

  await page.getByRole("button", { name: /Bu Sayfayı Çevir/ }).click();
  await confirmCost(page);
  await expect(page.locator(".engine-html")).toContainText("[TR] Replication means");
  await expect(page.getByTestId("spend")).toContainText("1 çağrı");
  await page.screenshot({ path: `${SHOTS}/02-sadece-ceviri.png` });
});

test("Split: block click highlights both sides, scroll is synchronized", async () => {
  await mode(page, "Split");
  const right = page.locator(".split .html-pane");
  await expect(right.locator(".engine-html")).toContainText("[TR]");
  const sentence = right.locator('[data-block="0-2"] [data-s="1"]');
  await sentence.click();
  await expect(page.getByTestId("pdf-highlight")).toBeVisible();
  await expect
    .poll(() => sentence.evaluate((el) => getComputedStyle(el).backgroundColor))
    .not.toBe("rgba(0, 0, 0, 0)");

  // Split fits the PDF to the pane width; a short window makes the page scroll vertically.
  await page.setViewportSize({ width: 1440, height: 560 });
  const left = page.locator(".split .pdf-pane");
  await expect.poll(() => left.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(1);
  await expect.poll(() => left.evaluate((el) => el.scrollHeight - el.clientHeight)).toBeGreaterThan(100);
  await left.evaluate((el) => (el.scrollTop = el.scrollHeight));
  await expect.poll(() => right.evaluate((el) => el.scrollTop)).toBeGreaterThan(0);
  await page.screenshot({ path: `${SHOTS}/03-split.png` });
  await page.setViewportSize({ width: 1440, height: 900 });
});

test("range job: progress, pause, resume, retry failed pages", async () => {
  await panel(page, "Kontrol");
  await page.getByPlaceholder("ör. 120-140").fill("2-4");
  await page.getByRole("button", { name: "Aralık Çevir" }).click();
  await confirmCost(page);

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

test("Tüm Kitabı Çevir: everything cached → no AI call needed", async () => {
  await panel(page, "Kontrol");
  await page.getByRole("button", { name: "Tüm Kitabı Çevir" }).click();
  const modal = page.getByRole("dialog", { name: /maliyet onayı/ });
  await expect(modal.getByTestId("cost-calls")).toHaveText("0");
  await expect(modal).toContainText("Tümü cache'te");
  await confirmCost(page);
  await expect(page.locator("article.job").first()).toContainText("Bitti", { timeout: 30_000 });
});

test("Kitabı Analiz Et → profile editor shows the result and saves edits", async () => {
  await panel(page, "Kontrol");
  await page.getByRole("button", { name: "Kitabı Analiz Et" }).click();
  await confirmCost(page);
  const editor = page.getByRole("region", { name: "Kitap profili" });
  await expect(editor.getByLabel("Tür")).toHaveValue("yazılım / veri sistemleri");
  await expect(editor.getByLabel("Terim", { exact: true }).first()).toHaveValue("replication");

  await editor.getByRole("button", { name: "+ Terim" }).click();
  await editor.getByLabel("Terim", { exact: true }).last().fill("leader");
  await editor.getByLabel("Karşılık", { exact: true }).last().fill("lider");
  await editor.getByLabel("Yeni çevrilmeyecek terim").fill("Kafka");
  await editor.getByLabel("Yeni çevrilmeyecek terim").press("Enter");
  await editor.getByRole("button", { name: "Kaydet" }).click();
  await expect(page.getByRole("status")).toContainText("Profil kaydedildi");

  await panel(page, "Kontrol");
  await panel(page, "Profil");
  await expect(editor.getByLabel("Terim", { exact: true }).last()).toHaveValue("leader");
  await expect(editor.locator(".chip", { hasText: "Kafka" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/06-profil.png` });
});

test("PDF Dışa Aktar produces a file without AI", async () => {
  await panel(page, "Kontrol");
  const before = await spend(page);
  await page.getByRole("button", { name: "PDF Dışa Aktar" }).click();
  await expect(page.getByRole("status")).toContainText("PDF hazır:", { timeout: 60_000 });
  expect(await spend(page)).toBe(before);
});

test("Öğrenme: click word → lookup → save unknown → ruby appears", async () => {
  await mode(page, "Öğrenme");
  const pane = page.locator(".html-pane.mode-learn");
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
  await panel(page, "Öğrenme");
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
});

test("Bunu açıkla: cost confirm first time, cached second time", async () => {
  const pane = page.locator(".html-pane.mode-learn");
  await pane.locator('[data-block="0-2"] [data-w="replication"]').first().click();
  const pop = page.getByRole("dialog", { name: "Sözlük: replication" });
  await pop.getByRole("button", { name: "Bunu açıkla…" }).click();
  await confirmCost(page);
  const box = page.getByRole("dialog", { name: "Açıklama" });
  await expect(box).toContainText("Sahte açıklama");
  await expect(box.locator("strong", { hasText: "Yapı:" })).toBeVisible();
  await expect(box).not.toContainText("**");
  await page.screenshot({ path: `${SHOTS}/09-aciklama.png` });
  await box.getByRole("button", { name: "Kapat" }).click();

  await pane.locator('[data-block="0-2"] [data-w="replication"]').first().click();
  await page.getByRole("dialog", { name: "Sözlük: replication" }).getByRole("button", { name: "Bunu açıkla…" }).click();
  await expect(page.getByRole("dialog", { name: /maliyet onayı/ })).toBeHidden();
  await expect(page.getByRole("dialog", { name: "Açıklama" })).toContainText("cache");
  await page.getByRole("dialog", { name: "Açıklama" }).getByRole("button", { name: "Kapat" }).click();
});
