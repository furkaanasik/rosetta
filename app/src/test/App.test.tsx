import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MockEngineApi } from "../api/mock";
import type { Estimate } from "../api/types";
import { App } from "../App";
import { CostModal } from "../components/CostModal";

vi.mock("../lib/pdf", () => ({
  loadPdf: vi.fn(),
  outline: vi.fn(async () => []),
}));

/** The toolbar's primary action (sheets inside the reader have their own "Bu sayfayı çevir"). */
const translateButton = () => screen.getByRole("button", { name: /Bu sayfayı çevir \(sayfa/ });

async function openBook(api: MockEngineApi) {
  vi.spyOn(window, "prompt").mockReturnValue("/books/kitap.pdf");
  const user = userEvent.setup();
  render(<App api={api} mock />);
  await user.click(await screen.findByRole("button", { name: "PDF aç" }));
  await screen.findByText("kitap", { selector: ".title" });
  return user;
}

describe("App shell", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("starts in the library and opens a book into the reader", async () => {
    const api = new MockEngineApi();
    await openBook(api);
    expect(screen.getByRole("navigation", { name: "Sayfa" })).toHaveTextContent("/ 12");
    expect(document.querySelector("main")).toHaveAttribute("data-mode", "split");
  });

  it("switches view modes (segmented control and 1–4 shortcuts)", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    const tabs = screen.getByRole("tablist", { name: "Görünüm modu" });
    for (const label of ["Orijinal", "Türkçe", "Öğrenme", "Yan yana"]) {
      await user.click(within(tabs).getByRole("tab", { name: label }));
      expect(within(tabs).getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    }
    fireEvent.keyDown(window, { key: "3" });
    expect(document.querySelector("main")).toHaveAttribute("data-mode", "translation");
    fireEvent.keyDown(window, { key: "1" });
    expect(document.querySelector("main")).toHaveAttribute("data-mode", "original");
  });

  it("translates only after the cost modal is confirmed", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    await user.click(translateButton());
    const dialog = await screen.findByRole("dialog", { name: /maliyet onayı/ });
    expect(api.aiCalls).toBe(0);

    await user.click(within(dialog).getByRole("button", { name: "İptal" }));
    expect(screen.queryByRole("dialog", { name: /maliyet onayı/ })).not.toBeInTheDocument();
    expect(api.aiCalls).toBe(0);

    await user.click(translateButton());
    await user.click(within(await screen.findByRole("dialog", { name: /maliyet onayı/ })).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(api.aiCalls).toBe(1));
    await screen.findByText("Sayfa 1 çevrildi.");
    await waitFor(() => expect(screen.getByTestId("spend")).toHaveTextContent("1 çağrı"));
  });

  it("T only opens the cost modal; it never translates by itself", async () => {
    const api = new MockEngineApi();
    await openBook(api);
    fireEvent.keyDown(window, { key: "t" });
    await screen.findByRole("dialog", { name: /maliyet onayı/ });
    expect(api.aiCalls).toBe(0);
  });

  it.each([
    ["Aralık çevir…", "range"],
    ["Tüm kitabı çevir…", "all"],
    ["Kitabı analiz et…", "analyze"],
    ["Bu sayfayı yeniden çevir…", "force"],
  ])("Çevir ▾ → %s goes through the cost modal", async (item, kind) => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    await user.click(screen.getByRole("button", { name: "Diğer çeviri seçenekleri" }));
    await user.click(await screen.findByRole("menuitem", { name: item }));
    if (kind === "range") {
      await user.type(await screen.findByPlaceholderText("ör. 120-140"), "1-2");
      await user.click(screen.getByRole("button", { name: "Aralığı çevir" }));
    } else if (kind === "all") {
      await user.click(await screen.findByRole("button", { name: "Tümünü çevir" }));
    }
    const dialog = await screen.findByRole("dialog", { name: /maliyet onayı/ });
    expect(api.aiCalls).toBe(0);
    await user.click(within(dialog).getByRole("button", { name: "İptal" }));
    expect(api.aiCalls).toBe(0);
  });

  it("command palette runs actions, AI ones only up to the cost modal", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    const palette = await screen.findByRole("dialog", { name: "Komut paleti" });
    await user.type(within(palette).getByRole("combobox"), "yeniden çevir");
    await user.keyboard("{Enter}");
    await screen.findByRole("dialog", { name: /maliyet onayı/ });
    expect(api.aiCalls).toBe(0);
  });

  it("side panel opens on its tab and keeps the table of contents", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    await user.click(screen.getByRole("button", { name: "Yan panel" }));
    const tabs = screen.getByRole("tablist", { name: "Paneller" });
    expect(within(tabs).getByRole("tab", { name: "İçindekiler" })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByRole("button", { name: /Leaders and Followers/ })).toBeInTheDocument();
    await user.click(within(tabs).getByRole("tab", { name: "Profil" }));
    expect(await screen.findByRole("region", { name: "Kitap profili" })).toBeInTheDocument();
  });

  it("returns to the library, which lists the book", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    await user.click(screen.getByRole("button", { name: "Kitaplık" }));
    const shelf = await screen.findByRole("region", { name: "Son açılanlar" });
    expect(within(shelf).getByText("kitap", { selector: ".book-card__title" })).toBeInTheDocument();
  });

  it("opens the PDF given at launch (?open=) without the picker", async () => {
    const api = new MockEngineApi();
    const spy = vi.spyOn(api, "openBook");
    const prompt = vi.spyOn(window, "prompt");
    window.history.pushState({}, "", "/?open=/books/kitap.pdf");
    try {
      render(<App api={api} mock />);
      await screen.findByText("kitap", { selector: ".title" });
      expect(spy).toHaveBeenCalledWith("/books/kitap.pdf");
      expect(prompt).not.toHaveBeenCalled();
    } finally {
      window.history.pushState({}, "", "/");
    }
  });

  it("without an engine the library says so and can't open books", () => {
    render(<App api={null} mock={false} engineError="motor başlamadı" />);
    expect(screen.getByRole("button", { name: "PDF aç" })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent("motor başlamadı");
  });
});

describe("CostModal", () => {
  const est: Estimate = {
    confirm_token: "t",
    operation: "translate",
    provider: "claude-cli",
    model: "sonnet",
    calls: 1,
    input_tokens: 2825,
    output_tokens: 4145,
    usd: 0.047,
    price_known: false,
    thinking: "medium",
    thinking_extra_tokens: 1500,
    total_blocks: 24,
    cached_blocks: 0,
    pages: [25],
    supports_profile: false,
    expires_in: 600,
  };

  it("shows unknown price, thinking and provider notes; confirm calls back", async () => {
    const onConfirm = vi.fn();
    const onCancel = vi.fn();
    render(<CostModal estimate={est} onConfirm={onConfirm} onCancel={onCancel} />);
    expect(screen.getByRole("dialog", { name: "Bu sayfayı çevir — maliyet onayı" })).toBeInTheDocument();
    expect(screen.getByTestId("cost-usd")).toHaveTextContent("fiyat bilinmiyor");
    expect(screen.getByTestId("cost-calls")).toHaveTextContent("1");
    expect(screen.getByText(/Düşünme: medium/)).toBeInTheDocument();
    expect(screen.getByText(/profilini ve bağlamı kullanmaz/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "İptal" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("says when everything is cached", () => {
    render(<CostModal estimate={{ ...est, calls: 0, price_known: true, usd: 0 }} onConfirm={() => undefined} onCancel={() => undefined} />);
    expect(screen.getByText(/Tümü önbellekte/)).toBeInTheDocument();
    act(() => undefined);
  });
});
