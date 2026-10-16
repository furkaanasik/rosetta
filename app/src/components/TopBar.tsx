import type { ViewMode } from "../api/types";
import { MODE_LABELS } from "../state";

interface Props {
  title: string | null;
  page: number;
  pageCount: number;
  zoom: number;
  mode: ViewMode;
  onOpen: () => void;
  onMode: (m: ViewMode) => void;
  onPage: (p: number) => void;
  onZoom: (z: number) => void;
  onToggleToc: () => void;
}

const MODES: ViewMode[] = ["original", "split", "translation", "learn"];

export function TopBar(p: Props) {
  return (
    <header className="topbar">
      <button type="button" onClick={p.onToggleToc} aria-label="İçindekiler panelini aç/kapat">
        ☰
      </button>
      <button type="button" onClick={p.onOpen}>
        PDF Aç
      </button>
      <span className="title" title={p.title ?? undefined}>
        {p.title ?? "Rosetta"}
      </span>
      <div className="segmented" role="tablist" aria-label="Görünüm modu">
        {MODES.map((m) => (
          <button
            key={m}
            type="button"
            role="tab"
            aria-selected={p.mode === m}
            className={p.mode === m ? "active" : ""}
            onClick={() => p.onMode(m)}
          >
            {MODE_LABELS[m]}
          </button>
        ))}
      </div>
      <nav className="pager" aria-label="Sayfa">
        <button type="button" onClick={() => p.onPage(p.page - 1)} disabled={p.page <= 1} aria-label="Önceki sayfa">
          ‹
        </button>
        <input
          aria-label="Sayfa numarası"
          type="number"
          min={1}
          max={p.pageCount || 1}
          value={p.page}
          onChange={(e) => p.onPage(Number(e.target.value))}
        />
        <span className="muted">/ {p.pageCount || "–"}</span>
        <button
          type="button"
          onClick={() => p.onPage(p.page + 1)}
          disabled={!p.pageCount || p.page >= p.pageCount}
          aria-label="Sonraki sayfa"
        >
          ›
        </button>
      </nav>
      <div className="zoom" aria-label="Yakınlaştırma">
        <button type="button" onClick={() => p.onZoom(p.zoom - 0.1)} aria-label="Uzaklaştır">
          −
        </button>
        <span>{Math.round(p.zoom * 100)}%</span>
        <button type="button" onClick={() => p.onZoom(p.zoom + 0.1)} aria-label="Yakınlaştır">
          +
        </button>
      </div>
    </header>
  );
}
