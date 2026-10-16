import {
  ArrowsOutLineHorizontal,
  BookOpenText,
  Books,
  CaretLeft,
  CaretRight,
  Columns,
  Command,
  FileText,
  GearSix,
  GraduationCap,
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
  SidebarSimple,
} from "@phosphor-icons/react";
import { forwardRef, useEffect, useState, type KeyboardEvent, type ReactNode } from "react";
import type { ViewMode } from "../api/types";
import { MODE_LABELS } from "../state";
import { cx, IconButton, Segmented, type SegmentedItem } from "../ui";
import { TranslateMenu, type RangeKind, type TranslateActions } from "./TranslateMenu";

const MODES: SegmentedItem<ViewMode>[] = [
  { value: "original", label: MODE_LABELS.original, icon: <FileText />, shortcut: "1" },
  { value: "split", label: MODE_LABELS.split, icon: <Columns />, shortcut: "2" },
  { value: "translation", label: MODE_LABELS.translation, icon: <BookOpenText />, shortcut: "3" },
  { value: "learn", label: MODE_LABELS.learn, icon: <GraduationCap />, shortcut: "4" },
];

interface Props {
  title: string;
  page: number;
  pageCount: number;
  /** Zoom actually shown (resolved while fitting). */
  zoom: number;
  fit: boolean;
  mode: ViewMode;
  hidden: boolean;
  panelOpen: boolean;
  translate: TranslateActions;
  rangeOpen: RangeKind | null;
  rangeSeed: string;
  onRangeOpen: (k: RangeKind | null) => void;
  onLibrary: () => void;
  onMode: (m: ViewMode) => void;
  onPage: (p: number) => void;
  onZoom: (z: number) => void;
  onFit: () => void;
  onTogglePanel: () => void;
  onPalette: () => void;
  /** Opens Ayarlar (Ctrl ,). */
  onSettings?: () => void;
  /** Quiet status (spend / engine state) shown at the end of the bar. */
  status?: ReactNode;
}

/** Page field: free typing, applied on Enter/blur (G focuses it). */
const PageField = forwardRef<HTMLInputElement, { page: number; pageCount: number; onPage: (p: number) => void }>(function PageField(
  { page, pageCount, onPage },
  ref,
) {
  const [draft, setDraft] = useState(String(page));
  useEffect(() => setDraft(String(page)), [page]);
  const commit = () => {
    const n = Number(draft);
    if (Number.isFinite(n) && n >= 1) onPage(n);
    else setDraft(String(page));
  };
  const onKey = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") {
      commit();
      e.currentTarget.blur();
    } else if (e.key === "Escape") {
      setDraft(String(page));
      e.currentTarget.blur();
    }
  };
  return (
    <input
      ref={ref}
      className="pager__input num"
      aria-label="Sayfa numarası"
      inputMode="numeric"
      value={draft}
      size={Math.max(2, String(pageCount).length)}
      onChange={(e) => setDraft(e.target.value.replace(/[^\d]/g, ""))}
      onBlur={commit}
      onKeyDown={onKey}
      onFocus={(e) => e.currentTarget.select()}
    />
  );
});

/**
 * Minimal reader chrome: library, title, view mode, page, zoom and the single primary
 * action (Çevir ▾). Hides while reading downwards; comes back on hover/scroll-up/shortcut.
 */
export const ReaderToolbar = forwardRef<HTMLInputElement, Props>(function ReaderToolbar(p, pageRef) {
  return (
    <header className={cx("topbar", p.hidden && "is-hidden")} data-hidden={p.hidden}>
      <div className="topbar__start">
        <IconButton label="Kitaplık" onClick={p.onLibrary}>
          <Books />
        </IconButton>
        <span className="title" title={p.title}>
          {p.title}
        </span>
        {p.status}
      </div>

      <div className="topbar__center">
        <Segmented<ViewMode> label="Görünüm modu" value={p.mode} items={MODES} onChange={p.onMode} className="mode-switch" />
      </div>

      <div className="topbar__end">
        <nav className="pager" aria-label="Sayfa">
          <IconButton label="Önceki sayfa" size="sm" onClick={() => p.onPage(p.page - 1)} disabled={p.page <= 1}>
            <CaretLeft />
          </IconButton>
          <PageField ref={pageRef} page={p.page} pageCount={p.pageCount} onPage={p.onPage} />
          <span className="pager__total num">/ {p.pageCount || "–"}</span>
          <IconButton label="Sonraki sayfa" size="sm" onClick={() => p.onPage(p.page + 1)} disabled={!p.pageCount || p.page >= p.pageCount}>
            <CaretRight />
          </IconButton>
        </nav>

        <div className="zoom" role="group" aria-label="Yakınlaştırma">
          <IconButton label="Uzaklaştır" title="Uzaklaştır (Ctrl −)" size="sm" onClick={() => p.onZoom(p.zoom - 0.1)}>
            <MagnifyingGlassMinus />
          </IconButton>
          <span className="zoom__value num" aria-live="polite">
            {Math.round(p.zoom * 100)}%
          </span>
          <IconButton label="Yakınlaştır" title="Yakınlaştır (Ctrl +)" size="sm" onClick={() => p.onZoom(p.zoom + 0.1)}>
            <MagnifyingGlassPlus />
          </IconButton>
          <IconButton label="Sayfaya sığdır" title="Sayfaya sığdır (Ctrl 0)" size="sm" aria-pressed={p.fit} onClick={p.onFit}>
            <ArrowsOutLineHorizontal />
          </IconButton>
        </div>

        <TranslateMenu {...p.translate} rangeOpen={p.rangeOpen} rangeSeed={p.rangeSeed} onRangeOpen={p.onRangeOpen} />

        <span className="topbar__sep" aria-hidden="true" />
        <IconButton label="Komut paleti" title="Komutlar (Ctrl K)" onClick={p.onPalette}>
          <Command />
        </IconButton>
        {p.onSettings && (
          <IconButton label="Ayarlar" title="Ayarlar (Ctrl ,)" onClick={p.onSettings}>
            <GearSix />
          </IconButton>
        )}
        <IconButton label="Yan panel" title="Yan panel (\)" aria-pressed={p.panelOpen} onClick={p.onTogglePanel}>
          <SidebarSimple />
        </IconButton>
      </div>
    </header>
  );
});
