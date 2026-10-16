import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import type { EngineApi } from "./api/engine";
import { isExplanation } from "./api/engine";
import { EngineError, type ExportMode, type Explanation, type UsageTotals } from "./api/types";
import { ControlPanel } from "./components/ControlPanel";
import { CostModal } from "./components/CostModal";
import { JobsPanel } from "./components/JobsPanel";
import { LearnPanel } from "./components/LearnPanel";
import { LookupPopover, type LookupTarget } from "./components/LookupPopover";
import { ProfileEditor } from "./components/ProfileEditor";
import { Sidebar } from "./components/Sidebar";
import { StatusBar } from "./components/StatusBar";
import { TopBar } from "./components/TopBar";
import { pdfSource, pickPdf } from "./lib/engineConnect";
import { parsePageSpec } from "./lib/format";
import { loadPdf, outline, type OutlineItem, type PdfDoc } from "./lib/pdf";
import { useConfirmed } from "./lib/useConfirmed";
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
};

interface Props {
  api: EngineApi | null;
  mock: boolean;
  /** Test hook: skip PDF.js loading. */
  loadDocument?: (src: string) => Promise<PdfDoc>;
}

export function App({ api, mock, loadDocument = loadPdf }: Props) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const [doc, setDoc] = useState<PdfDoc | null>(null);
  const [toc, setToc] = useState<OutlineItem[]>([]);
  const [usage, setUsage] = useState<UsageTotals | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [lookup, setLookup] = useState<LookupTarget | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const msgTimer = useRef<number | undefined>(undefined);

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

  const openBook = useCallback(async () => {
    if (!api) return;
    try {
      const path = await pickPdf();
      if (!path) return;
      const book = await api.openBook(path);
      const src = await pdfSource(path);
      dispatch({ type: "bookOpened", book, pdfSrc: src });
      if (src) {
        const d = await loadDocument(src);
        setDoc(d);
        setToc(await outline(d));
      } else {
        setDoc(null);
        const t = await api.toc(book.id);
        setToc(t.map((e) => ({ title: e.title, page: e.page, level: e.level })));
      }
    } catch (e) {
      onError(e);
    }
  }, [api, loadDocument, onError]);

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
        if (r.stop_kind) onError(new EngineError(r.stop_kind === "paused" ? "internal" : r.stop_kind, r.stopped_reason ?? ""));
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

  const analyze = () => {
    if (!api || bookId === null) return;
    void confirmed.request(
      () => api.estimateAnalyze(bookId),
      (t) => api.analyze(bookId, t),
      () => {
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
            onAnalyze={analyze}
            onTranslatePage={translatePage}
            onTranslateRange={translateRange}
            onTranslateAll={(budget) => startJob("all", budget)}
            onExport={(m) => void exportPdf(m)}
          />
        )}
        {state.panel === "jobs" && (
          <JobsPanel api={api} bookId={bookId} refreshKey={state.revision} requestConfirmed={(e, r, d) => void confirmed.request(e, r, d)} onChange={afterAi} />
        )}
        {state.panel === "profile" && <ProfileEditor api={api} bookId={bookId} refreshKey={state.revision} onAnalyze={analyze} onMessage={say} />}
        {state.panel === "learn" && <LearnPanel api={api} bookId={bookId} refreshKey={state.revision} onChange={afterAi} />}
      </aside>
      <StatusBar connected={api !== null} mock={mock} usage={usage} message={message} />
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
      {explanation && (
        <div className="modal-backdrop" role="presentation" onClick={() => setExplanation(null)}>
          <div className="modal" role="dialog" aria-modal="true" aria-label="Açıklama" onClick={(e) => e.stopPropagation()}>
            <h2>Açıklama {explanation.cached && <span className="badge done">cache</span>}</h2>
            <blockquote>{explanation.text}</blockquote>
            <p className="explanation">{explanation.explanation}</p>
            <div className="modal-actions">
              <button type="button" onClick={() => setExplanation(null)}>Kapat</button>
            </div>
          </div>
        </div>
      )}
      {confirmed.pending && (
        <CostModal estimate={confirmed.pending.estimate} busy={confirmed.busy} onConfirm={() => void confirmed.confirm()} onCancel={confirmed.cancel} />
      )}
    </div>
  );
}
