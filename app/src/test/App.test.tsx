import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MockEngineApi } from "../api/mock";
import { App } from "../App";
import { CostModal } from "../components/CostModal";
import type { Estimate } from "../api/types";

vi.mock("../lib/pdf", () => ({
  loadPdf: vi.fn(),
  outline: vi.fn(async () => []),
}));

async function openBook(api: MockEngineApi) {
  vi.spyOn(window, "prompt").mockReturnValue("/books/kitap.pdf");
  const user = userEvent.setup();
  render(<App api={api} mock />);
  await user.click(screen.getByRole("button", { name: "PDF Aç" }));
  await screen.findByText("kitap");
  return user;
}

describe("App", () => {
  afterEach(() => vi.restoreAllMocks());

  it("switches view modes", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    const tabs = screen.getByRole("tablist", { name: "Görünüm modu" });
    for (const label of ["Orijinal", "Sadece Çeviri", "Öğrenme", "Split"]) {
      await user.click(within(tabs).getByRole("tab", { name: label }));
      expect(within(tabs).getByRole("tab", { name: label })).toHaveAttribute("aria-selected", "true");
    }
    await user.click(within(tabs).getByRole("tab", { name: "Sadece Çeviri" }));
    expect(document.querySelector("main")).toHaveAttribute("data-mode", "translation");
    await screen.findByText(/henüz çevrilmedi/);
  });

  it("translates only after the cost modal is confirmed", async () => {
    const api = new MockEngineApi();
    const user = await openBook(api);
    await user.click(screen.getByRole("button", { name: /Bu Sayfayı Çevir/ }));
    const dialog = await screen.findByRole("dialog", { name: /maliyet onayı/ });
    expect(api.aiCalls).toBe(0);

    await user.click(within(dialog).getByRole("button", { name: "İptal" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(api.aiCalls).toBe(0);

    await user.click(screen.getByRole("button", { name: /Bu Sayfayı Çevir/ }));
    await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(api.aiCalls).toBe(1));
    await screen.findByText("Sayfa çevrildi.");
    await waitFor(() => expect(screen.getByTestId("spend")).toHaveTextContent("1 çağrı"));
  });

  it("disables AI buttons without an engine", () => {
    render(<App api={null} mock={false} />);
    expect(screen.getByRole("button", { name: "Kitabı Analiz Et" })).toBeDisabled();
    expect(screen.getByRole("button", { name: /Bu Sayfayı Çevir/ })).toHaveAttribute("title", "Motor bağlı değil");
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
    expect(screen.getByTestId("cost-usd")).toHaveTextContent("fiyat bilinmiyor");
    expect(screen.getByText(/Düşünme: medium/)).toBeInTheDocument();
    expect(screen.getByText(/profilini ve bağlamı kullanmaz/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "İptal" })).toHaveFocus();
    await userEvent.click(screen.getByRole("button", { name: "Onayla" }));
    expect(onConfirm).toHaveBeenCalledOnce();
    expect(onCancel).not.toHaveBeenCalled();
  });
});
