import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MOCK_DEFAULT_SETTINGS, MockEngineApi } from "../api/mock";
import { EngineError } from "../api/types";
import { App } from "../App";
import { describeError } from "../lib/errors";
import { draftOf, patchOf, SettingsScreen, thinkingOf, thinkingPatch } from "../settings/SettingsScreen";
import { ToastProvider, TipProvider } from "../ui";

vi.mock("../lib/pdf", () => ({
  loadPdf: vi.fn(),
  outline: vi.fn(async () => []),
}));

function renderSettings(api = new MockEngineApi(), section?: Parameters<typeof SettingsScreen>[0]["section"]) {
  const onClose = vi.fn();
  render(
    <TipProvider>
      <ToastProvider>
        <SettingsScreen api={api} theme="system" onTheme={() => undefined} onClose={onClose} section={section} />
      </ToastProvider>
    </TipProvider>,
  );
  return { api, onClose, user: userEvent.setup() };
}

describe("settings form logic", () => {
  it("maps the thinking control to effort + MAX_THINKING_TOKENS", () => {
    expect(thinkingOf({ claude_effort: "medium", claude_max_thinking_tokens: null })).toBe("medium");
    expect(thinkingOf({ claude_effort: "low", claude_max_thinking_tokens: 0 })).toBe("off");
    expect(thinkingPatch("off")).toEqual({ claude_effort: "low", claude_max_thinking_tokens: 0 });
    expect(thinkingPatch("high")).toEqual({ claude_effort: "high", claude_max_thinking_tokens: null });
  });

  it("sends only changed keys and validates inputs", () => {
    const saved = { ...MOCK_DEFAULT_SETTINGS };
    const d = draftOf(saved);
    expect(patchOf(d, saved).patch).toEqual({});

    const { patch, errors } = patchOf({ ...d, model: "haiku", claude_max_budget_usd: "0,5", thinking: "off" }, saved);
    expect(errors).toEqual({});
    expect(patch).toEqual({ model: "haiku", claude_max_budget_usd: 0.5, claude_effort: "low", claude_max_thinking_tokens: 0 });

    const bad = patchOf({ ...d, claude_max_budget_usd: "-1", ollama_url: "localhost", claude_path: "claude" }, saved);
    expect(Object.keys(bad.errors).sort()).toEqual(["claude_max_budget_usd", "claude_path", "ollama_url"]);
  });

  it("clears a budget back to 'no limit' with an empty field", () => {
    const saved = { ...MOCK_DEFAULT_SETTINGS };
    expect(patchOf({ ...draftOf(saved), claude_max_budget_usd: "" }, saved).patch).toEqual({ claude_max_budget_usd: null });
  });
});

describe("SettingsScreen", () => {
  beforeEach(() => localStorage.clear());

  it("saves changed settings and shows the result", async () => {
    const { api, user } = renderSettings();
    const put = vi.spyOn(api, "putSettings");
    const save = await screen.findByRole("button", { name: "Kaydet" });
    expect(save).toBeDisabled();

    const thinking = screen.getByRole("tablist", { name: "Düşünme seviyesi" });
    await user.click(within(thinking).getByRole("tab", { name: "Kapalı" }));
    expect(screen.getByText("Kaydedilmemiş değişiklikler")).toBeInTheDocument();
    await user.click(save);

    await waitFor(() => expect(put).toHaveBeenCalledWith({ claude_effort: "low", claude_max_thinking_tokens: 0 }));
    expect(await screen.findByText("Ayarlar kaydedildi")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Kaydet" })).toBeDisabled();
  });

  it("shows inline validation errors without calling the engine", async () => {
    const { api, user } = renderSettings();
    const put = vi.spyOn(api, "putSettings");
    const url = await screen.findByDisplayValue("http://localhost:11434");
    await user.clear(url);
    await user.type(url, "localhost");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));

    expect(await screen.findByText("http(s)://sunucu:port biçiminde olmalı")).toBeInTheDocument();
    expect(put).not.toHaveBeenCalled();
  });

  it("fills the claude path from the Bul results", async () => {
    const { user } = renderSettings(undefined, "claude");
    await user.click(await screen.findByRole("button", { name: "Bul" }));
    const list = await screen.findByRole("list", { name: "Bulunan claude kurulumları" });
    await user.click(within(list).getByRole("button"));

    expect(screen.getByPlaceholderText("Otomatik bul")).toHaveValue("/home/mock/.local/bin/claude");
  });

  it("lists engine diagnostics", async () => {
    renderSettings();
    expect(await screen.findByText("claude CLI")).toBeInTheDocument();
    expect(screen.getByText(/662\.319 madde/)).toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const { onClose, user } = renderSettings();
    await screen.findByRole("button", { name: "Kaydet" });
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalled();
  });
});

describe("error messages", () => {
  it("tells engine-down, provider-missing and busy apart", () => {
    expect(describeError(new EngineError("offline", "x")).message).toMatch(/Motor bağlantısı yok/);
    const missing = describeError(new EngineError("unavailable", "claude CLI bulunamadı — Ayarlar'dan yolunu girin"));
    expect(missing).toEqual({ message: "claude CLI bulunamadı — Ayarlar'dan yolunu girin", action: "settings" });
    const busy = describeError(new EngineError("busy", "Toplu iş #2 çalışıyor; şu anki parti bitince tekrar deneyin"));
    expect(busy.action).toBe("jobs");
    expect(busy.message).toContain("#2");
  });

  it("opens Ayarlar from the 'claude bulunamadı' toast action", async () => {
    const api = new MockEngineApi();
    vi.spyOn(window, "prompt").mockReturnValue("/books/kitap.pdf");
    vi.spyOn(api, "estimateTranslate").mockRejectedValue(
      new EngineError("unavailable", "claude CLI bulunamadı — Ayarlar'dan yolunu girin", 503),
    );
    const user = userEvent.setup();
    render(<App api={api} mock />);
    await user.click(await screen.findByRole("button", { name: "PDF aç" }));
    await screen.findByText("kitap", { selector: ".title" });
    await user.click(screen.getByRole("button", { name: /Bu sayfayı çevir \(sayfa/ }));

    expect(await screen.findByText("claude CLI bulunamadı — Ayarlar'dan yolunu girin")).toBeInTheDocument();
    const toasts = screen.getByRole("status");
    await user.click(within(toasts).getByRole("button", { name: "Ayarlar" }));
    expect(await screen.findByRole("dialog", { name: "Ayarlar" })).toBeInTheDocument();
  });

  it("opens Ayarlar from the library header and with Ctrl+,", async () => {
    const user = userEvent.setup();
    render(<App api={new MockEngineApi()} mock />);
    await user.click(await screen.findByRole("button", { name: "Ayarlar" }));
    expect(await screen.findByRole("dialog", { name: "Ayarlar" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Geri (Esc)" }));
    expect(screen.queryByRole("dialog", { name: "Ayarlar" })).not.toBeInTheDocument();
    await user.keyboard("{Control>},{/Control}");
    expect(await screen.findByRole("dialog", { name: "Ayarlar" })).toBeInTheDocument();
  });
});
