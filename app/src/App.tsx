import {
  ArrowClockwise,
  ArrowsOutLineHorizontal,
  Books,
  BookOpenText,
  Cards,
  Columns,
  Export,
  FilePdf,
  FileText,
  FolderOpen,
  GearSix,
  GraduationCap,
  ListBullets,
  MagicWand,
  Moon,
  PushPin,
  Rows,
  SlidersHorizontal,
  Stack,
  Translate,
} from "@phosphor-icons/react";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import type { EngineApi } from "./api/engine";
import { isExplanation } from "./api/engine";
import { EngineError, type BlockRef, type ExportMode, type Explanation, type UsageTotals, type ViewMode } from "./api/types";
import { CommandPalette, type PaletteAction } from "./components/CommandPalette";
import { CostModal } from "./components/CostModal";
import { ExplanationPanel } from "./components/ExplanationPanel";
import { JobsPanel } from "./components/JobsPanel";
import { ConsistencyPanel } from "./components/ConsistencyPanel";
import { LearnPanel } from "./components/LearnPanel";
import { LookupPopover, type LookupTarget } from "./components/LookupPopover";
import { ProfileEditor } from "./components/ProfileEditor";
import { ReaderToolbar } from "./components/ReaderToolbar";
import { SidePanel } from "./components/SidePanel";
import { SpendPill } from "./components/SpendPill";
import { TocList } from "./components/TocList";
import type { RangeKind, TranslateActions } from "./components/TranslateMenu";
import { Library } from "./library/Library";
import { initialPdf, onEngineError, onOpenPdf, pdfSource, pickPdf } from "./lib/engineConnect";
import { describeError, ERROR_ACTION_LABEL } from "./lib/errors";
import { SettingsScreen, type SettingsSection } from "./settings/SettingsScreen";
import { parsePageSpec, stopReasonText } from "./lib/format";
import { loadPdf, outline, type OutlineItem, type PdfDoc } from "./lib/pdf";
import { useConfirmed } from "./lib/useConfirmed";
import { ReaderCanvas } from "./reader/ReaderCanvas";
import { fitZoom, MAX_ZOOM as READER_MAX_ZOOM } from "./reader/geometry";
import { initialState, MODE_LABELS, reducer, type SidePanel as PanelTab } from "./state";
import { TipProvider, ToastProvider, usePref, useShortcuts, useTheme, useToast, type ShortcutMap } from "./ui";

const MODE_KEY = "rosetta.mode";
/** Fit-to-width never blows a single page past this (a 1920 px window would otherwise read at ~230 %). */
const SINGLE_FIT_CAP = 1.5;
const MODES: ViewMode[] = ["original", "split", "translation", "learn"];

function storedMode(): ViewMode | null {
  try {
    const v = localStorage.getItem(MODE_KEY);
    return MODES.includes(v as ViewMode) ? (v as ViewMode) : null;
  } catch {
    return null;
  }
}

interface Props {
  api: EngineApi | null;
  mock: boolean;
  /** Why the engine isn't available (start-up failure). */
  engineError?: string | null;
  /** Test hook: skip PDF.js loading. */
  loadDocument?: (src: string | ArrayBuffer) => Promise<PdfDoc>;
}

/** Frees a PDF.js document (worker-side data); test doubles may not implement it. */
function releaseDoc(d: PdfDoc | null): void {
  void (d as { destroy?: () => Promise<void> } | null)?.destroy?.()?.catch(() => undefined);
}

export function App(props: Props) {
  return (
    <TipProvider delayDuration={350} skipDelayDuration={200}>
      <ToastProvider>
        <Shell {...props} />
      </ToastProvider>
    </TipProvider>
  );
}

function Shell({ api, mock, engineError = null, loadDocument = loadPdf }: Props) {
  const [state, dispatch] = useReducer(reducer, initialState, (s) => ({ ...s, mode: storedMode() ?? s.mode }));
  const [doc, setDoc] = useState<PdfDoc | null>(null);
  const [toc, setToc] = useState<OutlineItem[]>([]);
  const [usage, setUsage] = useState<UsageTotals | null>(null);
  const [lookup, setLookup] = useState<(LookupTarget & { page: number }) | null>(null);
  const [explanation, setExplanation] = useState<Explanation | null>(null);
  const [engineDown, setEngineDown] = useState<string | null>(engineError);
  const [areaWidth, setAreaWidth] = useState(0);
  const [widestPt, setWidestPt] = useState(0);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [rangeOpen, setRangeOpen] = useState<RangeKind | null>(null);
  const [rangeSeed, setRangeSeed] = useState("");
  const [chromeHidden, setChromeHidden] = useState(false);
  const [libraryKey, setLibraryKey] = useState(0);
  const [theme, setTheme, cycleTheme] = useTheme();
  const [settingsAt, setSettingsAt] = useState<SettingsSection | null>(null);
  const [jobBudget, setJobBudget] = useState<number | null>(null);
  const [pinned, setPinned] = usePref("rosetta.chrome.pinned", false);
  const toast = useToast();
  const docRef = useRef<PdfDoc | null>(null);
  const openSeq = useRef(0);
  const pageInput = useRef<HTMLInputElement>(null);
  const readerRef = useRef<HTMLDivElement>(null);
  const mainRef = useRef<HTMLElement>(null);

  const say = useCallback((m: string) => void toast({ message: m, tone: "success" }), [toast]);

  const onError = useCallback(
    (e: unknown) => {
      const { message, action } = describeError(e);
      toast({
        message,
        tone: "error",
        action: action
          ? {
              label: ERROR_ACTION_LABEL[action],
              onClick: () => (action === "settings" ? setSettingsAt("claude") : dispatch({ type: "panel", panel: "jobs" })),
            }
          : undefined,
      });
    },
    [toast],
  );

  const confirmed = useConfirmed(onError);

  useEffect(() => {
    if (!api) return;
    let alive = true;
    api
      .getSettings()
      .then((v) => alive && setJobBudget(v.values.job_default_budget_usd))
      .catch(() => undefined); // older engines: no settings endpoint, keep the empty default
    return () => {
      alive = false;
    };
  }, [api]);
  const bookId = state.book?.id ?? null;
  const reading = state.screen === "reader" && state.book !== null;

  // Fit-to-width, computed here so single-page modes can be capped (the reader fits uncapped).
  useEffect(() => {
    if (!api || bookId === null) return setWidestPt(0);
    let cancelled = false;
    api
      .pages(bookId)
      .then((ps) => !cancelled && setWidestPt(ps.reduce((w, p) => Math.max(w, p.width), 0)))
      .catch(() => !cancelled && setWidestPt(0));
    return () => {
      cancelled = true;
    };
  }, [api, bookId]);
  useEffect(() => {
    const el = mainRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const measure = () => setAreaWidth((el.querySelector<HTMLElement>(".rs-canvas") ?? el).clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [reading]);
  const columns = state.mode === "split" ? 2 : 1;
  const fitted = widestPt > 0 && areaWidth > 0 ? Math.min(fitZoom(widestPt, areaWidth, columns), columns === 2 ? READER_MAX_ZOOM : SINGLE_FIT_CAP) : null;
  const shownZoom = state.fit && fitted !== null ? fitted : state.zoom;

  useEffect(() => {
    try {
      localStorage.setItem(MODE_KEY, state.mode);
    } catch {
      /* ignore */
    }
  }, [state.mode]);

  useEffect(() => {
    document.title = reading && state.book ? `${state.book.title} — Rosetta` : "Rosetta";
  }, [reading, state.book]);

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

  const openPath = useCallback(
    async (path: string) => {
      if (!api) return;
      // Latest open wins: a slower, older open never mixes its book with another file's document/TOC.
      const seq = ++openSeq.current;
      const stale = () => seq !== openSeq.current;
      try {
        const book = await api.openBook(path);
        const src = await pdfSource(path);
        if (stale()) return;
        // Resume where the reader left off (library v2; older engines just start at page 1).
        const last = await api
          .listBooks()
          .then((list) => list.find((b) => b.id === book.id)?.last_page ?? null)
          .catch(() => null);
        if (stale()) return;
        setToc([]);
        dispatch({ type: "bookOpened", book, pdfSrc: src, page: last ?? 1 });
        if (last && last > 1) {
          toast({
            message: `Kaldığınız yer: sayfa ${last}`,
            tone: "info",
            action: { label: "Başa dön", onClick: () => dispatch({ type: "goto", page: 1 }) },
          });
        }
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
    },
    [api, loadDocument, onError, showDoc, toast],
  );

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

  const afterAi = useCallback(() => dispatch({ type: "refresh" }), []);

  // ---- AI actions: all go estimate → CostModal → Onayla → run (rules 1–2) ----
  const translatePage = useCallback(
    (page: number = state.page, force = false) => {
      if (!api || bookId === null) return;
      void confirmed.request(
        () => api.estimateTranslate(bookId, force ? { pages: [page], force: true } : { pages: [page] }),
        (t) => api.translate(bookId, t),
        (r) => {
          const failed = Object.keys(r.failed_pages).length;
          if (failed) toast({ message: `${failed} sayfa çevrilemedi: ${Object.values(r.failed_pages)[0] ?? ""}`, tone: "warning" });
          else say(`Sayfa ${page} çevrildi.`);
          if (r.stop_kind) onError(new EngineError(r.stop_kind === "paused" ? "internal" : r.stop_kind, stopReasonText(r.stopped_reason ?? "")));
          afterAi();
        },
      );
    },
    [api, bookId, confirmed, state.page, say, toast, onError, afterAi],
  );

  // Targeted re-translation from the Tutarlılık panel: estimate → CostModal → only after Onayla.
  const retranslateBlocks = (blocks: BlockRef[], term: string) => {
    if (!api || bookId === null || blocks.length === 0) return;
    void confirmed.request(
      () => api.estimateTranslate(bookId, { pages: [], blocks }),
      (t) => api.translate(bookId, t),
      (r) => {
        const failed = Object.keys(r.failed_pages).length;
        if (failed) toast({ message: `${failed} sayfada yeniden çeviri başarısız: ${Object.values(r.failed_pages)[0] ?? ""}`, tone: "warning" });
        else say(`“${term}” geçen ${blocks.length} paragraf yeniden çevrildi.`);
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
        say(`Çeviri işi #${job.id} başladı.`);
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
      const preparing = toast({ message: mode === "tr" ? "Türkçe PDF hazırlanıyor…" : "İki dilli PDF hazırlanıyor…", duration: 120_000 });
      const r = await api.exportPdf(bookId, { mode }).finally(preparing);
      const extra = r.untranslated_blocks ? ` · ${r.untranslated_blocks} paragraf çevrilmemiş` : "";
      toast({
        message: `PDF hazır — ${r.pages} sayfa${extra}`,
        tone: "success",
        duration: 8000,
        action: { label: "Yolu kopyala", onClick: () => void navigator.clipboard?.writeText(r.path).catch(() => undefined) },
      });
    } catch (e) {
      onError(e);
    }
  };

  const explain = async (text: string, page: number) => {
    if (!api) return;
    try {
      const first = await api.estimateExplain({ text, book_id: bookId ?? undefined, page });
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

  const onWordClick = useCallback((word: string, sentence: string, blockKey: string | null, page?: number) => {
    const w = word.trim();
    if (w) setLookup({ word: w, sentence, blockKey, page: page ?? currentPage.current });
  }, []);

  const onPageChange = useCallback((page: number) => dispatch({ type: "goto", page }), []);
  const openRangeFrom = useCallback(
    (from: number) => {
      const count = state.book?.page_count ?? from;
      setRangeSeed(`${from}-${Math.min(count, from + 19)}`);
      setChromeHidden(false);
      setRangeOpen("range");
    },
    [state.book],
  );

  const openFromLibrary = useCallback((path: string) => void openPath(path), [openPath]);

  const goLibrary = useCallback(() => {
    dispatch({ type: "library" });
    setLibraryKey((k) => k + 1);
  }, []);

  // ---- chrome auto-hide: down hides, up / hover at the top / any shortcut shows ----
  const lastScroll = useRef(0);
  const holdChrome = pinned || rangeOpen !== null || paletteOpen || confirmed.pending !== null;
  useEffect(() => {
    if (holdChrome) setChromeHidden(false);
  }, [holdChrome]);
  useEffect(() => {
    const el = readerRef.current;
    if (!el) return;
    // Only the reader's own scrolling (wheel, touch, keys) hides the bar — never a jump to a
    // page from the page field, the TOC or a shortcut.
    let intent = 0;
    const markIntent = () => {
      intent = Date.now();
    };
    const onKey = (e: KeyboardEvent) => {
      if (["PageDown", "PageUp", "ArrowDown", "ArrowUp", " ", "Home", "End"].includes(e.key)) markIntent();
    };
    const onScroll = (e: Event) => {
      const t = e.target;
      if (!(t instanceof HTMLElement) || !t.classList.contains("rs-canvas")) return;
      const y = t.scrollTop;
      const dy = y - lastScroll.current;
      lastScroll.current = y;
      if (Date.now() - intent > 400) return;
      if (holdChrome || el.querySelector(".topbar [data-state='open'], .topbar :focus")) return;
      if (dy > 6 && y > 120) setChromeHidden(true);
      else if (dy < -6) setChromeHidden(false);
    };
    el.addEventListener("wheel", markIntent, { capture: true, passive: true });
    el.addEventListener("touchmove", markIntent, { capture: true, passive: true });
    el.addEventListener("keydown", onKey, { capture: true });
    el.addEventListener("scroll", onScroll, { capture: true, passive: true });
    return () => {
      el.removeEventListener("wheel", markIntent, { capture: true });
      el.removeEventListener("touchmove", markIntent, { capture: true });
      el.removeEventListener("keydown", onKey, { capture: true });
      el.removeEventListener("scroll", onScroll, { capture: true });
    };
  }, [holdChrome, reading]);

  const translateActions: TranslateActions = {
    disabledReason: !api ? "Motor bağlı değil" : bookId === null ? "Önce bir PDF açın" : null,
    busy: confirmed.busy,
    page: state.page,
    pageCount: state.book?.page_count ?? 0,
    onTranslatePage: () => translatePage(),
    onRetranslatePage: () => translatePage(state.page, true),
    onTranslateRange: translateRange,
    onTranslateAll: (budget) => startJob("all", budget),
    onAnalyze: () => analyze(),
    onExport: (m) => void exportPdf(m),
    defaultBudget: jobBudget,
  };
  const canAi = translateActions.disabledReason === null;

  // ---- keyboard ----
  const show = () => setChromeHidden(false);
  const step = (d: number) => {
    show();
    dispatch({ type: "goto", page: state.page + d });
  };
  const zoomBy = (d: number) => {
    show();
    dispatch({ type: "zoom", zoom: shownZoom + d });
  };
  const shortcuts: ShortcutMap = {
    "mod+k": () => setPaletteOpen((o) => !o),
    "mod+o": () => void openBook(),
    "mod+,": () => setSettingsAt((s) => (s ? null : "translate")),
  };
  if (reading && !settingsAt) {
    Object.assign(shortcuts, {
      "1": () => dispatch({ type: "mode", mode: "original" }),
      "2": () => dispatch({ type: "mode", mode: "split" }),
      "3": () => dispatch({ type: "mode", mode: "translation" }),
      "4": () => dispatch({ type: "mode", mode: "learn" }),
      arrowleft: () => step(-1),
      arrowright: () => step(1),
      pageup: () => step(-1),
      pagedown: () => step(1),
      k: () => step(-1),
      j: () => step(1),
      g: () => {
        show();
        window.setTimeout(() => pageInput.current?.focus(), 0);
      },
      "mod+=": () => zoomBy(0.1),
      "mod++": () => zoomBy(0.1),
      "mod+-": () => zoomBy(-0.1),
      "mod+0": () => dispatch({ type: "fit" }),
      t: () => canAi && translatePage(),
      "\\": () => dispatch({ type: "togglePanel" }),
      escape: () => {
        if (lookup) setLookup(null);
        else if (state.panelOpen) dispatch({ type: "closePanel" });
      },
    } satisfies ShortcutMap);
  }
  useShortcuts(shortcuts);

  // ---- command palette ----
  const panelAction = (panel: PanelTab, label: string, icon: ReactNode): PaletteAction => ({
    id: `panel-${panel}`,
    label,
    group: "Paneller",
    icon,
    run: () => dispatch({ type: "panel", panel }),
  });
  const actions = useMemo<PaletteAction[]>(() => {
    const list: PaletteAction[] = [
      { id: "open", label: "PDF aç…", group: "Uygulama", icon: <FolderOpen />, shortcut: "Ctrl O", disabled: !api, run: () => void openBook() },
      { id: "library", label: "Kitaplığa dön", group: "Uygulama", icon: <Books />, disabled: !reading, run: goLibrary },
      { id: "settings", label: "Ayarlar", group: "Uygulama", icon: <GearSix />, shortcut: "Ctrl ,", keywords: ["tercihler", "claude", "yol", "model"], run: () => setSettingsAt("translate") },
      { id: "theme", label: "Temayı değiştir (sistem / koyu / açık)", group: "Uygulama", icon: <Moon />, keywords: ["karanlık", "tema"], run: cycleTheme },
      {
        id: "pin",
        label: pinned ? "Üst çubuğu otomatik gizle" : "Üst çubuğu her zaman göster",
        group: "Uygulama",
        icon: <PushPin />,
        run: () => setPinned(!pinned),
      },
    ];
    if (!reading) return list;
    return [
      { id: "tr-page", label: "Bu sayfayı çevir", group: "Çeviri", icon: <Translate />, shortcut: "T", disabled: !canAi, run: () => translatePage() },
      { id: "tr-force", label: "Bu sayfayı yeniden çevir", group: "Çeviri", icon: <ArrowClockwise />, disabled: !canAi, run: () => translatePage(state.page, true) },
      { id: "tr-range", label: "Aralık çevir…", group: "Çeviri", icon: <Rows />, disabled: !canAi, run: () => openRangeFrom(state.page) },
      {
        id: "tr-all",
        label: "Tüm kitabı çevir…",
        group: "Çeviri",
        icon: <Books />,
        disabled: !canAi,
        run: () => {
          setChromeHidden(false);
          setRangeOpen("all");
        },
      },
      ...MODES.map<PaletteAction>((m, i) => ({
        id: `mode-${m}`,
        label: `Görünüm: ${MODE_LABELS[m]}`,
        group: "Görünüm",
        icon: [<FileText key="o" />, <Columns key="s" />, <BookOpenText key="t" />, <GraduationCap key="l" />][i],
        shortcut: String(i + 1),
        run: () => dispatch({ type: "mode", mode: m }),
      })),
      { id: "fit", label: "Sayfaya sığdır", group: "Görünüm", icon: <ArrowsOutLineHorizontal />, shortcut: "Ctrl 0", run: () => dispatch({ type: "fit" }) },
      { id: "first", label: "İlk sayfaya git", group: "Git", run: () => dispatch({ type: "goto", page: 1 }) },
      { id: "last", label: "Son sayfaya git", group: "Git", run: () => dispatch({ type: "goto", page: state.book?.page_count ?? 1 }) },
      panelAction("toc", "İçindekiler", <ListBullets />),
      panelAction("jobs", "Çeviri işleri", <Stack />),
      panelAction("words", "Kelimeler ve tekrar", <Cards />),
      panelAction("profile", "Kitap profili", <SlidersHorizontal />),
      { id: "analyze", label: "Kitabı analiz et…", group: "Kitap", icon: <MagicWand />, disabled: !canAi, run: () => analyze() },
      { id: "export-tr", label: "PDF olarak dışa aktar — Türkçe", group: "Kitap", icon: <FilePdf />, disabled: !api, run: () => void exportPdf("tr") },
      { id: "export-bi", label: "PDF olarak dışa aktar — iki dilli", group: "Kitap", icon: <Export />, disabled: !api, run: () => void exportPdf("bilingual") },
      ...list,
    ];
    // Recomputed on every render anyway (cheap); the deps that matter are listed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, reading, canAi, pinned, state.page, state.book, cycleTheme, goLibrary, openBook, openRangeFrom, translatePage]);

  const overlays = (
    <>
      <CommandPalette
        open={paletteOpen}
        onOpenChange={setPaletteOpen}
        actions={actions}
        pageCount={reading ? (state.book?.page_count ?? 0) : 0}
        onGoto={(page) => dispatch({ type: "goto", page })}
      />
      {lookup && api && (
        <LookupPopover
          api={api}
          target={lookup}
          bookId={bookId}
          page={lookup.page}
          onClose={() => setLookup(null)}
          onSaved={afterAi}
          onExplain={(t) => {
            const page = lookup.page;
            setLookup(null);
            void explain(t, page);
          }}
        />
      )}
      {explanation && <ExplanationPanel explanation={explanation} onClose={() => setExplanation(null)} />}
      {settingsAt && (
        <SettingsScreen
          api={api}
          mock={mock}
          theme={theme}
          onTheme={setTheme}
          section={settingsAt}
          onClose={() => setSettingsAt(null)}
          onSaved={(v) => {
            setJobBudget(v.values.job_default_budget_usd);
            dispatch({ type: "refresh" });
          }}
        />
      )}
      {confirmed.pending && (
        <CostModal estimate={confirmed.pending.estimate} busy={confirmed.busy} onConfirm={() => void confirmed.confirm()} onCancel={confirmed.cancel} />
      )}
    </>
  );

  if (!reading || !state.book) {
    return (
      <div className="app" data-screen="library">
        <Library
          api={api}
          mock={mock}
          engineError={engineDown}
          refreshKey={libraryKey}
          theme={theme}
          onTheme={cycleTheme}
          onPick={() => void openBook()}
          onOpenPath={openFromLibrary}
          onSettings={() => setSettingsAt("translate")}
        />
        {overlays}
      </div>
    );
  }

  return (
    <div
      ref={readerRef}
      className="app reader"
      data-screen="reader"
      data-chrome={chromeHidden ? "hidden" : "shown"}
      onMouseMove={(e) => {
        if (chromeHidden && e.clientY < 64) setChromeHidden(false);
      }}
      onFocusCapture={(e) => {
        if (chromeHidden && (e.target as HTMLElement).closest?.(".topbar")) setChromeHidden(false);
      }}
    >
      <ReaderToolbar
        ref={pageInput}
        title={state.book.title}
        page={state.page}
        pageCount={state.book.page_count}
        zoom={shownZoom}
        fit={state.fit}
        mode={state.mode}
        hidden={chromeHidden}
        panelOpen={state.panelOpen}
        translate={translateActions}
        rangeOpen={rangeOpen}
        rangeSeed={rangeSeed}
        onRangeOpen={(k) => {
          if (k === "range" && rangeOpen === null && !rangeSeed) setRangeSeed("");
          setRangeOpen(k);
        }}
        onLibrary={goLibrary}
        onMode={(mode) => dispatch({ type: "mode", mode })}
        onPage={(page) => dispatch({ type: "goto", page })}
        onZoom={(zoom) => dispatch({ type: "zoom", zoom })}
        onFit={() => dispatch({ type: "fit" })}
        onTogglePanel={() => dispatch({ type: "togglePanel" })}
        onPalette={() => setPaletteOpen(true)}
        onSettings={() => setSettingsAt("translate")}
        status={<SpendPill inline connected={api !== null && engineDown === null} mock={mock} usage={usage} error={engineDown} />}
      />
      <main ref={mainRef} className="reader__main" data-mode={state.mode}>
        <ReaderCanvas
          api={api}
          bookId={bookId}
          doc={doc}
          pageCount={state.book.page_count}
          mode={state.mode}
          zoom={shownZoom}
          // Until the page sizes are known the reader fits by itself.
          fit={state.fit && fitted === null}
          page={state.page}
          revision={state.revision}
          onPageChange={onPageChange}
          onWordClick={onWordClick}
          onTranslatePage={(page) => translatePage(page)}
          onTranslateRange={openRangeFrom}
          toc={toc}
        />
      </main>
      <SidePanel
        open={state.panelOpen}
        tab={state.panel}
        onTab={(panel) => dispatch({ type: "panel", panel })}
        onClose={() => dispatch({ type: "closePanel" })}
        toc={<TocList items={toc} current={state.page} onGo={(page) => dispatch({ type: "goto", page })} />}
        jobs={
          <JobsPanel
            api={api}
            bookId={bookId}
            refreshKey={state.revision}
            requestConfirmed={(e, r, d) => void confirmed.request(e, r, d)}
            onProgress={onJobProgress}
            onError={onError}
          />
        }
        words={<LearnPanel api={api} bookId={bookId} refreshKey={state.revision} onChange={afterAi} />}
        profile={<ProfileEditor api={api} bookId={bookId} refreshKey={state.revision} onAnalyze={analyze} onMessage={say} />}
        consistency={
          <ConsistencyPanel
            api={api}
            bookId={bookId}
            refreshKey={state.revision}
            onGoto={(page) => dispatch({ type: "goto", page })}
            onRetranslate={retranslateBlocks}
            onChanged={afterAi}
            onMessage={say}
          />
        }
      />
      {overlays}
    </div>
  );
}
