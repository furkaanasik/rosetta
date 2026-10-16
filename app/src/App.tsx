import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { EngineApi } from "./api/engine";
import { isExplanation } from "./api/engine";
import { EngineError, type ExportMode, type Explanation, type UsageTotals } from "./api/types";
import { ControlPanel } from "./components/ControlPanel";
import { CostModal } from "./components/CostModal";
import { ExplanationText } from "./components/ExplanationText";
import { JobsPanel } from "./components/JobsPanel";
import { LearnPanel } from "./components/LearnPanel";
import { LookupPopover, type LookupTarget } from "./components/LookupPopover";
import { ProfileEditor } from "./components/ProfileEditor";
import { Sidebar } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { initialPdf, onEngineError, onOpenPdf, pdfSource, pickPdf } from "./lib/engineConnect";
import { parsePageSpec, stopReasonText } from "./lib/format";
import { loadPdf, outline, type OutlineItem, type PdfDoc } from "./lib/pdf";
import { useConfirmed } from "./lib/useConfirmed";
import { useModalFocus } from "./lib/useModalFocus";
import { initialState, reducer, type SidePanel } from "./state";
import { PdfPageView } from "./views/PdfPageView";
import { SplitView } from "./views/SplitView";
import { TranslationPane } from "./views/TranslationPane";

const ERROR_TEXT: Partial<Record<EngineError["kind"], string>> = {
  usage_limit: "Kullanım limitine ulaşıldı — iş duraklatıldı.",
  auth: "Claude girişi yok: terminalde `claude` ile giriş yapın.",
  budget: "Bütçe sınırı aşıldı — durdu.",
  unavailable: "Sağlayıcı/motor kullanılamıyor.",
  expired_token: "Onayın süresi doldu; tahmini yeniden alın.",
  conflict: "Kitap dosyası kayıtlı yolda değişmiş; PDF'i yeniden açın.",
};

interface Props {
  api: EngineApi | null;
  mock: boolean;
  /** Why the engine isn't available (start-up failure), shown in the status bar. */
  engineError?: string | null;
  /** Test hook: skip PDF.js loading. */
  loadDocument?: (src: string | ArrayBuffer) => Promise<PdfDoc>;
}

/** Frees a PDF.js document (worker-side data); test doubles may not implement it. */
function releaseDoc(d: PdfDoc | null): void {
  void (d as { destroy?: () => Promise<void> } | null)?.destroy?.()?.catch(() => undefined);
}

export function App({ api, mock, engineError = null, loadDocument = loadPdf }: Props) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [doc, setDoc] = useState<PdfDoc | null>(null);
  const [toc, setToc] = useState<OutlineItem[]>([]);
  const [usage, setUsage] = useState<UsageTotals | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [lookup, setLookup] = useState<LookupTarget | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [engineDown, setEngineDown] = useState<string | null>(engineError);
  const msgTimer = useRef<number | undefined>(undefined);
  const docRef = useRef<PdfDoc | null>(null);
  const openSeq = useRef(0);

  const say = useCallback((m: string) => {
    setMessage(m);
    window.clearTimeout(msgTimer.current);
    msgTimer.current = window.setTimeout(() => setMessage(null), 8000);
  }, []);

  const onError = useCallback(
    (e: unknown) => {
      if (e instanceof EngineError) say(ERROR_TEXT[e.kind] ?? e.message);
      else say(e instanceof Error ? e.message : String(e));
    },
    [say],
  );

  const confirmed = useConfirmed(onError);
  const bookId = state.book?.id ?? null;

  const refreshUsage = useCallback(() => {
    if (api) void api.usage().then(setUsage).catch(() => undefined);
  }, [api]);

  useEffect(refreshUsage, [refreshUsage, state.revision]);

  // Engine crash/exit after start-up (Tauri).
  useEffect(() => {
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    void onEngineError((m) => setEngineDown(m)).then((u) => {
      if (cancelled) u();
      else unlisten = u;
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, []);

  const showDoc = useCallback((d: PdfDoc | null) => {
    const old = docRef.current;
    docRef.current = d;
    setDoc(d);
    if (old && old !== d) releaseDoc(old);
  }, []);

  useEffect(() => () => releaseDoc(docRef.current), []);

  const openPath = useCallback(async (path: string) => {
    if (!api) return;
    // Latest open wins: a slower, older open (e.g. a hand-over during a load) never mixes its
    // book with another file's document/TOC.
    const seq = ++openSeq.current;
    const stale = () => seq !== openSeq.current;
    try {
      const book = await api.openBook(path);
      const src = await pdfSource(path);
      if (stale()) return;
      dispatch({ type: "bookOpened", book, pdfSrc: src });
      // In Tauri the file is loaded directly; in a plain browser (dev/E2E) it comes from the engine.
      const data = src ?? (await api.bookFile(book.id));
      if (stale()) return;
      if (data) {
        const d = await loadDocument(data);
        if (stale()) return releaseDoc(d);
        showDoc(d);
        const items = await outline(d);
        if (!stale()) setToc(items);
      } else {
        showDoc(null);
        const t = await api.toc(book.id);
        if (!stale()) setToc(t.map((e) => ({ title: e.title, page: e.page, level: e.level })));
      }
    } catch (e) {
      if (!stale()) onError(e);
    }
  }, [api, loadDocument, onError, showDoc]);

  const openBook = useCallback(async () => {
    if (!api) return;
    try {
      const path = await pickPdf();
      if (path) await openPath(path);
    } catch (e) {
      onError(e);
    }
  }, [api, openPath, onError]);

  // "Open with Rosetta" / `rosetta kitap.pdf`: the launch argument, then later hand-overs. The
  // listener is registered first and the pending path drained after, so nothing is lost.
  useEffect(() => {
    if (!api) return;
    let cancelled = false;
    let unlisten: (() => void) | undefined;
    const drain = () =>
      void initialPdf()
        .then((path) => {
          if (path && !cancelled) void openPath(path);
        })
        .catch(onError);
    void onOpenPdf(drain).then((u) => {
      if (cancelled) u();
      else unlisten = u;
      drain();
    });
    return () => {
      cancelled = true;
      unlisten?.();
    };
  }, [api, openPath, onError]);

  const afterAi = useCallback(() => {
    dispatch({ type: "refresh" });
  }, []);

  const translatePage = () => {
    if (!api || bookId === null) return;
    void confirmed.request(
      () => api.estimateTranslate(bookId, { pages: [state.page] }),
      (t) => api.translate(bookId, t),
      (r) => {
        const failed = Object.keys(r.failed_pages).length;
        say(failed ? `${failed} sayfa hatalı: ${Object.values(r.failed_pages)[0] ?? ""}` : "Sayfa çevrildi.");
        if (r.stop_kind) onError(new EngineError(r.stop_kind === "paused" ? "internal" : r.stop_kind, stopReasonText(r.stopped_reason ?? "")));
        afterAi();
      },
    );
  };

  const startJob = (pages: number[] | "all", budget: number | null) => {
    if (!api || bookId === null) return;
    void confirmed.request(
      () => api.estimateJob(bookId, pages === "all" ? { pages: [], all: true, budget_usd: budget } : { pages, budget_usd: budget }),
      (t) => api.startJob(t),
      (job) => {
        say(`İş #${job.id} başladı.`);
        dispatch({ type: "panel", panel: "jobs" });
        afterAi();
      },
    );
  };

  const translateRange = (spec: string, budget: number | null) => {
    if (!state.book) return;
    try {
      startJob(parsePageSpec(spec, state.book.page_count), budget);
    } catch (e) {
      onError(e);
    }
  };

  const analyze = (onAnalyzed?: () => void) => {
    if (!api || bookId === null) return;
    void confirmed.request(
      () => api.estimateAnalyze(bookId),
      (t) => api.analyze(bookId, t),
      () => {
        onAnalyzed?.();
        say("Kitap profili oluşturuldu.");
        dispatch({ type: "panel", panel: "profile" });
        afterAi();
      },
    );
  };

  const exportPdf = async (mode: ExportMode) => {
    if (!api || bookId === null) return;
    try {
      say("Dışa aktarılıyor…");
      const r = await api.exportPdf(bookId, { mode });
      say(`PDF hazır: ${r.path} (${r.pages} sayfa${r.untranslated_blocks ? `, ${r.untranslated_blocks} çevrilmemiş block` : ""})`);
    } catch (e) {
      onError(e);
    }
  };

  const explain = async (text: string) => {
    if (!api) return;
    try {
      const first = await api.estimateExplain({ text, book_id: bookId ?? undefined, page: state.page });
      if (isExplanation(first)) {
        setExplanation(first);
        return;
      }
      await confirmed.request(
        async () => first,
        (t) => api.explain(t),
        (r) => {
          setExplanation(r);
          afterAi();
        },
      );
    } catch (e) {
      onError(e);
    }
  };

  // Job progress: usage always; page views only when the visible page (or a whole job) changed.
  const currentPage = useRef(state.page);
  currentPage.current = state.page;
  const onJobProgress = useCallback(
    (done: number[], stopped: boolean) => {
      refreshUsage();
      if (stopped || done.includes(currentPage.current)) dispatch({ type: "refresh" });
    },
    [refreshUsage],
  );

  const onWordClick = useCallback((word: string, sentence: string, blockKey: string | null) => {
    const w = word.trim();
    if (w) setLookup({ word: w, sentence, blockKey });
  }, []);

  const panelTabs: { id: SidePanel; label: string }[] = [
    { id: "control", label: "Kontrol" },
    { id: "jobs", label: "İşler" },
    { id: "profile", label: "Profil" },
    { id: "learn", label: "Öğrenme" },
  ];

  return (
    <div className={`app ${state.tocOpen ? "with-toc" : ""}`}>
      <TopBar
        title={state.book?.title ?? null}
        page={state.page}
        pageCount={state.book?.page_count ?? 0}
        zoom={state.zoom}
        mode={state.mode}
        onOpen={() => void openBook()}
        onMode={(mode) => dispatch({ type: "mode", mode })}
        onPage={(page) => dispatch({ type: "goto", page })}
        onZoom={(zoom) => dispatch({ type: "zoom", zoom })}
        onToggleToc={() => dispatch({ type: "toggleToc" })}
      />
      {state.tocOpen && <Sidebar items={toc} current={state.page} onGo={(page) => dispatch({ type: "goto", page })} />}
      <main className="main" data-mode={state.mode}>
        {state.mode === "original" && <PdfPageView doc={doc} page={state.page} zoom={state.zoom} />}
        {state.mode === "split" && (
          <SplitView api={api} bookId={bookId} doc={doc} page={state.page} zoom={state.zoom} revision={state.revision} onWordClick={onWordClick} />
        )}
        {state.mode === "translation" && (
          <TranslationPane api={api} bookId={bookId} page={state.page} mode="tr" revision={state.revision} onWordClick={onWordClick} />
        )}
        {state.mode === "learn" && (
          <TranslationPane api={api} bookId={bookId} page={state.page} mode="learn" revision={state.revision} onWordClick={onWordClick} />
        )}
      </main>
      <aside className="rightbar">
        <div className="tabs" role="tablist" aria-label="Paneller">
          {panelTabs.map((t) => (
            <button key={t.id} type="button" role="tab" aria-selected={state.panel === t.id} className={state.panel === t.id ? "active" : ""} onClick={() => dispatch({ type: "panel", panel: t.id })}>
              {t.label}
            </button>
          ))}
        </div>
        {state.panel === "control" && (
          <ControlPanel
            connected={api !== null}
            hasBook={bookId !== null}
            page={state.page}
            busy={confirmed.busy}
            onAnalyze={() => analyze()}
            onTranslatePage={translatePage}
            onTranslateRange={translateRange}
            onTranslateAll={(budget) => startJob("all", budget)}
            onExport={(m) => void exportPdf(m)}
          />
        )}
        {state.panel === "jobs" && (
          <JobsPanel api={api} bookId={bookId} refreshKey={state.revision} requestConfirmed={(e, r, d) => void confirmed.request(e, r, d)} onProgress={onJobProgress} onError={onError} />
        )}
        {state.panel === "profile" && <ProfileEditor api={api} bookId={bookId} refreshKey={state.revision} onAnalyze={analyze} onMessage={say} />}
        {state.panel === "learn" && <LearnPanel api={api} bookId={bookId} refreshKey={state.revision} onChange={afterAi} />}
      </aside>
      <StatusBar connected={api !== null && engineDown === null} mock={mock} usage={usage} message={message} error={engineDown} />
      {lookup && api && (
        <LookupPopover
          api={api}
          target={lookup}
          bookId={bookId}
          page={state.page}
          onClose={() => setLookup(null)}
          onSaved={afterAi}
          onExplain={(t) => {
            setLookup(null);
            void explain(t);
          }}
        />
      )}
      {explanation && <ExplanationDialog explanation={explanation} onClose={() => setExplanation(null)} />}
      {confirmed.pending && (
        <CostModal estimate={confirmed.pending.estimate} busy={confirmed.busy} onConfirm={() => void confirmed.confirm()} onCancel={confirmed.cancel} />
      )}
    </div>
  );
}

function ExplanationDialog({ explanation, onClose }: { explanation: Explanation; onClose: () => void }) {
  const dialog = useRef<HTMLDivElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  useModalFocus(dialog, onClose, close);
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <div ref={dialog} tabIndex={-1} className="modal" role="dialog" aria-modal="true" aria-label="Açıklama" onClick={(e) => e.stopPropagation()}>
        <h2>Açıklama {explanation.cached && <span className="badge done">cache</span>}</h2>
        <blockquote>{explanation.text}</blockquote>
        <ExplanationText text={explanation.explanation} />
        <div className="modal-actions">
          <button ref={close} type="button" onClick={onClose}>Kapat</button>
        </div>
      </div>
    </div>
  );
}
