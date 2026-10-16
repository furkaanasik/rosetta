import { act, fireEvent, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import type { EngineApi } from "../api/engine";
import { MockEngineApi } from "../api/mock";
import type { BookProfile, Estimate, Job } from "../api/types";
import { CostModal } from "../components/CostModal";
import { JobsPanel } from "../components/JobsPanel";
import { ProfileEditor } from "../components/ProfileEditor";
import { useConfirmed } from "../lib/useConfirmed";

const est: Estimate = {
  confirm_token: "t1",
  operation: "translate",
  provider: "claude-cli",
  model: "sonnet",
  calls: 1,
  input_tokens: 10,
  output_tokens: 10,
  usd: 0.01,
  price_known: true,
  thinking: null,
  thinking_extra_tokens: 0,
  total_blocks: 1,
  cached_blocks: 0,
  pages: [1],
  supports_profile: true,
  expires_in: 600,
};

describe("CostModal warnings", () => {
  it("shows estimate warnings before confirmation", () => {
    render(
      <CostModal
        estimate={{ ...est, warnings: ["Fiyat bilinmediği için bütçe önceden uygulanamaz."] }}
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("bütçe önceden uygulanamaz");
  });
});

describe("CostModal keyboard and focus", () => {
  it("Escape anywhere cancels, and focus returns to the opener", async () => {
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setOpen(true)}>Çevir</button>
          <p>arka plan</p>
          {open && <CostModal estimate={est} onConfirm={() => undefined} onCancel={() => setOpen(false)} />}
        </>
      );
    }
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Çevir" });
    await user.click(opener);
    expect(screen.getByRole("button", { name: "İptal" })).toHaveFocus();
    // Focus moved out of the dialog (e.g. a click on plain text): Escape still cancels.
    (document.activeElement as HTMLElement).blur();
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("ignores Escape while the confirmed call is running", () => {
    const onCancel = vi.fn();
    render(<CostModal estimate={est} busy onConfirm={() => undefined} onCancel={onCancel} />);
    fireEvent.keyDown(document.body, { key: "Escape" });
    expect(onCancel).not.toHaveBeenCalled();
  });

  it("keeps Tab inside the dialog", async () => {
    const user = userEvent.setup();
    render(
      <>
        <button type="button">dışarıda</button>
        <CostModal estimate={est} onConfirm={() => undefined} onCancel={() => undefined} />
      </>,
    );
    const cancel = screen.getByRole("button", { name: "İptal" });
    const confirm = screen.getByRole("button", { name: "Onayla" });
    expect(cancel).toHaveFocus();
    await user.tab();
    expect(confirm).toHaveFocus();
    await user.tab();
    expect(cancel).toHaveFocus();
    await user.tab({ shift: true });
    expect(confirm).toHaveFocus();
  });
});

describe("useConfirmed", () => {
  it("never swaps the shown estimate and can't cancel a running call", async () => {
    const onError = vi.fn();
    const { result } = renderHook(() => useConfirmed(onError));
    await act(() => result.current.request(async () => est, async () => "a"));
    expect(result.current.pending?.estimate.confirm_token).toBe("t1");

    // A second request while one is shown is ignored.
    await act(() => result.current.request(async () => ({ ...est, confirm_token: "t2" }), async () => "b"));
    expect(result.current.pending?.estimate.confirm_token).toBe("t1");

    let release: (v: string) => void = () => undefined;
    const run = vi.fn(() => new Promise<string>((r) => (release = r)));
    act(() => result.current.cancel());
    await act(() => result.current.request(async () => est, run));
    let confirming: Promise<void> = Promise.resolve();
    act(() => {
      confirming = result.current.confirm();
    });
    act(() => result.current.cancel()); // ignored: the call is in flight
    expect(result.current.pending).not.toBeNull();
    await act(async () => {
      release("done");
      await confirming;
    });
    expect(run).toHaveBeenCalledOnce();
    expect(result.current.pending).toBeNull();
    expect(onError).not.toHaveBeenCalled();
  });
});

function job(over: Partial<Job>): Job {
  return {
    id: 1,
    book_id: 1,
    status: "pending",
    pages: [1, 2, 3],
    done_pages: [],
    failed_pages: {},
    spent_usd: 0,
    budget_usd: null,
    stop_reason: null,
    created_at: "",
    updated_at: "",
    ...over,
  } as Job;
}

describe("JobsPanel polling", () => {
  afterEach(() => vi.useRealTimers());

  it("polls pending jobs and reports only newly finished pages", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const states = [job({ status: "pending" }), job({ status: "running", done_pages: [2] }), job({ status: "done", done_pages: [1, 2, 3] })];
    let i = 0;
    const api = {
      listJobs: vi.fn(async () => [states[Math.min(i, states.length - 1)]!]),
      getJob: vi.fn(async () => states[Math.min(i, states.length - 1)]!),
    } as unknown as EngineApi;
    const onProgress = vi.fn();
    render(<JobsPanel api={api} bookId={1} refreshKey={0} requestConfirmed={() => undefined} onProgress={onProgress} onError={() => undefined} />);
    await screen.findByText("Bekliyor");
    i = 1;
    await act(() => vi.advanceTimersByTimeAsync(1600));
    await screen.findByText("Çalışıyor");
    expect(onProgress).toHaveBeenLastCalledWith([2], false);
    i = 2;
    await act(() => vi.advanceTimersByTimeAsync(1600));
    await screen.findByText("Bitti");
    expect(onProgress).toHaveBeenLastCalledWith([1, 3], true);
    const calls = (api.listJobs as ReturnType<typeof vi.fn>).mock.calls.length;
    await act(() => vi.advanceTimersByTimeAsync(5000));
    expect((api.listJobs as ReturnType<typeof vi.fn>).mock.calls.length).toBe(calls); // stopped polling
  });

  it("reports load errors instead of leaving them unhandled", async () => {
    const api = { listJobs: vi.fn(async () => Promise.reject(new Error("bağlantı yok"))) } as unknown as EngineApi;
    const onError = vi.fn();
    render(<JobsPanel api={api} bookId={1} refreshKey={0} requestConfirmed={() => undefined} onProgress={() => undefined} onError={onError} />);
    await waitFor(() => expect(onError).toHaveBeenCalled());
  });
});

describe("ProfileEditor", () => {
  it("keeps unsaved edits when the analysis is cancelled", async () => {
    const api = new MockEngineApi();
    const profile: BookProfile = { tur: "eski", ton: "", hedef_dil: "tr", cevrilmeyecek: [], sozluk: {}, kod_dili: [] };
    vi.spyOn(api, "getProfile").mockResolvedValue(profile);
    let analyzed: (() => void) | null = null;
    const user = userEvent.setup();
    const { rerender } = render(
      <ProfileEditor api={api} bookId={1} refreshKey={0} onAnalyze={(done) => (analyzed = done)} onMessage={() => undefined} />,
    );
    const tur = await screen.findByDisplayValue("eski");
    await user.clear(tur);
    await user.type(tur, "yeni");
    await user.click(screen.getByRole("button", { name: /Kitabı Analiz Et/ }));
    // User pressed İptal in the cost modal: onDone never runs; a later refresh must not wipe edits.
    rerender(<ProfileEditor api={api} bookId={1} refreshKey={1} onAnalyze={(done) => (analyzed = done)} onMessage={() => undefined} />);
    await act(async () => undefined);
    expect(screen.getByDisplayValue("yeni")).toBeInTheDocument();

    // After a real analysis the server profile replaces the edits.
    act(() => analyzed?.());
    rerender(<ProfileEditor api={api} bookId={1} refreshKey={2} onAnalyze={() => undefined} onMessage={() => undefined} />);
    await screen.findByDisplayValue("eski");
  });
});
