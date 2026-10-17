import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EngineApi } from "../api/engine";
import { MockEngineApi } from "../api/mock";
import type { BlockRef, ConsistencyReport } from "../api/types";
import { ConsistencyPanel } from "../components/ConsistencyPanel";
import { CostModal } from "../components/CostModal";
import { ProfileEditor } from "../components/ProfileEditor";
import { useConfirmed } from "../lib/useConfirmed";

async function mockApi() {
  const api = new MockEngineApi();
  const book = await api.openBook("/books/ddia.pdf");
  return { api, bookId: book.id };
}

/** The panel wired like App: re-translation goes estimate → CostModal → Onayla. */
function Harness({ api, bookId, onMessage = () => undefined, onChanged = () => undefined }: {
  api: EngineApi;
  bookId: number;
  onMessage?: (m: string) => void;
  onChanged?: () => void;
}) {
  const confirmed = useConfirmed(() => undefined);
  const retranslate = (blocks: BlockRef[]) =>
    void confirmed.request(
      () => api.estimateTranslate(bookId, { pages: [], blocks }),
      (t) => api.translate(bookId, t),
    );
  return (
    <>
      <ConsistencyPanel
        api={api}
        bookId={bookId}
        refreshKey={0}
        onGoto={() => undefined}
        onRetranslate={retranslate}
        onChanged={onChanged}
        onMessage={onMessage}
      />
      {confirmed.pending && (
        <CostModal estimate={confirmed.pending.estimate} busy={confirmed.busy} onConfirm={() => void confirmed.confirm()} onCancel={confirmed.cancel} />
      )}
    </>
  );
}

describe("ConsistencyPanel", () => {
  it("lists glossary and discovered terms in separate sections", async () => {
    const { api, bookId } = await mockApi();
    render(<Harness api={api} bookId={bookId} />);

    expect(await screen.findByText(/2 olası tutarsızlık/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Sözlük terimleri/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Keşfedilen terimler/ })).toBeInTheDocument();
    const card = screen.getByRole("article", { name: "replication" });
    expect(within(card).getByText("çoğaltma")).toBeInTheDocument();
    expect(within(card).getByText("×3")).toBeInTheDocument();
  });

  it("'Sözlüğe ekle' saves to the glossary without AI and reports affected paragraphs", async () => {
    const { api, bookId } = await mockApi();
    const accept = vi.spyOn(api, "acceptTerm");
    const estimate = vi.spyOn(api, "estimateTranslate");
    const onMessage = vi.fn();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(<Harness api={api} bookId={bookId} onMessage={onMessage} onChanged={onChanged} />);

    const card = await screen.findByRole("article", { name: "replication" });
    const row = within(card).getByText("çoğaltma").closest("li")!;
    await user.click(within(row as HTMLElement).getByRole("button", { name: "Sözlüğe ekle" }));

    expect(accept).toHaveBeenCalledWith(bookId, "replication", "çoğaltma");
    await waitFor(() => expect(onMessage).toHaveBeenCalledWith(expect.stringMatching(/Sözlüğe eklendi: replication → çoğaltma · 3 paragraf/)));
    expect(onChanged).toHaveBeenCalled();
    expect(estimate).not.toHaveBeenCalled();
    expect(api.aiCalls).toBe(0);
    expect((await api.getProfile(bookId))?.sozluk).toEqual({ replication: "çoğaltma" });
  });

  it("'Yeniden çevir' only estimates; translation runs after Onayla, never on İptal", async () => {
    const { api, bookId } = await mockApi();
    const estimate = vi.spyOn(api, "estimateTranslate");
    const translate = vi.spyOn(api, "translate");
    const user = userEvent.setup();
    render(<Harness api={api} bookId={bookId} />);

    const card = await screen.findByRole("article", { name: "leader" });
    await user.click(within(card).getByRole("button", { name: /Uyumsuz 2 paragrafı yeniden çevir/ }));

    expect(estimate).toHaveBeenCalledWith(bookId, {
      pages: [],
      blocks: [
        { page: 3, text_hash: "mock-3" },
        { page: 7, text_hash: "mock-7" },
      ],
    });
    const dialog = await screen.findByRole("dialog", { name: /maliyet onayı/ });
    expect(translate).not.toHaveBeenCalled();
    await user.click(within(dialog).getByRole("button", { name: "İptal" }));
    expect(translate).not.toHaveBeenCalled();
    expect(api.aiCalls).toBe(0);

    await user.click(within(card).getByRole("button", { name: /yeniden çevir/ }));
    await user.click(within(await screen.findByRole("dialog", { name: /maliyet onayı/ })).getByRole("button", { name: "Onayla" }));
    await waitFor(() => expect(translate).toHaveBeenCalledTimes(1));
    expect(api.aiCalls).toBe(1);
  });

  it("'Yok say' hides the term and it can be restored", async () => {
    const { api, bookId } = await mockApi();
    const user = userEvent.setup();
    render(<Harness api={api} bookId={bookId} />);

    const card = await screen.findByRole("article", { name: "leader" });
    await user.click(within(card).getByRole("button", { name: "Yok say" }));
    await waitFor(() => expect(screen.queryByRole("article", { name: "leader" })).not.toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: /leader/ }));
    expect(await screen.findByRole("article", { name: "leader" })).toBeInTheDocument();
  });

  it("shows an empty state when nothing is translated yet", async () => {
    const { api, bookId } = await mockApi();
    const empty: ConsistencyReport = {
      lang: "tr",
      provider: "claude-cli",
      model: "sonnet",
      analyzed_blocks: 0,
      aligned_ratio: 1,
      ignored: [],
      issues: [],
    };
    vi.spyOn(api, "consistency").mockResolvedValue(empty);
    render(<Harness api={api} bookId={bookId} />);
    expect(await screen.findByText("Henüz çevrilmiş sayfa yok")).toBeInTheDocument();
  });
});

describe("ProfileEditor keeps terms added from the consistency panel", () => {
  it("merges a glossary term added elsewhere while it had unsaved edits", async () => {
    const { api, bookId } = await mockApi();
    await api.putProfile(bookId, { tur: "", ton: "", hedef_dil: "tr", cevrilmeyecek: [], sozluk: { latency: "gecikme" }, kod_dili: [] });
    const user = userEvent.setup();
    render(<ProfileEditor api={api} bookId={bookId} refreshKey={0} onAnalyze={() => undefined} onMessage={() => undefined} />);

    const tur = await screen.findByPlaceholderText(/yazılım/);
    await waitFor(() => expect(screen.getByDisplayValue("gecikme")).toBeInTheDocument());
    await user.type(tur, "teknik");
    await act(async () => {
      await api.acceptTerm(bookId, "replication", "çoğaltma");
    });
    const put = vi.spyOn(api, "putProfile");
    await user.click(screen.getByRole("button", { name: "Kaydet" }));

    await waitFor(() => expect(put).toHaveBeenCalled());
    const saved = put.mock.calls[0]![1];
    expect(saved.tur).toBe("teknik");
    expect(saved.sozluk).toEqual({ latency: "gecikme", replication: "çoğaltma" });
  });
});
