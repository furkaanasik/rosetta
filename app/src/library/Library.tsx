import { FilePlus, GearSix, Moon, Plug, Sun, SunHorizon, WarningCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { LibraryBook } from "../api/types";
import { useLatest } from "../lib/useLatest";
import { cx, IconButton, Kbd, Skeleton, type ThemePref } from "../ui";
import { percent, relativeTime } from "../ui/text";
import { Cover } from "./Cover";
import { onPdfDrop, type DropState } from "./dragDrop";

interface Props {
  api: EngineApi | null;
  mock: boolean;
  engineError: string | null;
  /** Bumped when the library may have changed (book opened, pages translated). */
  refreshKey: number;
  theme: ThemePref;
  onTheme: () => void;
  onPick: () => void;
  onOpenPath: (path: string) => void;
  /** Opens Ayarlar (Ctrl ,). */
  onSettings?: () => void;
}

const THEME_ICON = { system: <SunHorizon />, light: <Sun />, dark: <Moon /> };
const THEME_LABEL = { system: "Tema: sistem", light: "Tema: açık", dark: "Tema: koyu" };

/** Home screen: recently opened books (cover, progress, translated share) and "PDF aç". */
export function Library({ api, mock, engineError, refreshKey, theme, onTheme, onPick, onOpenPath, onSettings }: Props) {
  const [books, setBooks] = useState<LibraryBook[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drop, setDrop] = useState<DropState>("idle");
  const latest = useLatest();
  const connected = api !== null && engineError === null;

  const load = useCallback(() => {
    if (!api) {
      setBooks([]);
      return;
    }
    void latest(
      api.listBooks(),
      (list) => {
        setBooks(list);
        setError(null);
      },
      (e: unknown) => {
        setBooks([]);
        setError(e instanceof Error ? e.message : String(e));
      },
    );
  }, [api, latest]);

  useEffect(load, [load, refreshKey]);

  useEffect(() => {
    let cancelled = false;
    let off: (() => void) | undefined;
    void onPdfDrop({ state: setDrop, drop: onOpenPath }).then((u) => {
      if (cancelled) u();
      else off = u;
    });
    return () => {
      cancelled = true;
      off?.();
    };
  }, [onOpenPath]);

  return (
    <div className={cx("library", drop === "over" && "is-dropping")}>
      <header className="library__bar">
        <div className="brand">
          <span className="brand__mark" aria-hidden="true">
            R
          </span>
          <span className="brand__name">Rosetta</span>
        </div>
        <div className="library__status">
          <span className={cx("dot", connected ? "dot--ok" : "dot--off")} aria-hidden="true" />
          <span>{connected ? (mock ? "Deneme motoru" : "Motor bağlı") : "Motor bağlı değil"}</span>
          {engineError && (
            <span className="library__error" title={engineError}>
              — {engineError}
            </span>
          )}
        </div>
        <IconButton label={THEME_LABEL[theme]} onClick={onTheme}>
          {THEME_ICON[theme]}
        </IconButton>
        {onSettings && (
          <IconButton label="Ayarlar" title="Ayarlar (Ctrl ,)" onClick={onSettings}>
            <GearSix />
          </IconButton>
        )}
      </header>

      <main className="library__main">
        <section className="library__hero">
          <h1 className="library__title">Kitaplık</h1>
          <p className="library__lede">Bir PDF açın; orijinali okuyun, istediğiniz sayfayı Türkçeye çevirin.</p>
        </section>

        <button type="button" className="dropzone" onClick={onPick} disabled={!api} aria-label="PDF aç">
          <span className="dropzone__icon" aria-hidden="true">
            <FilePlus />
          </span>
          <span className="dropzone__text">
            <strong>PDF aç</strong>
            <span className="muted">ya da dosyayı bu pencereye sürükleyin</span>
          </span>
          <span className="dropzone__kbd" aria-hidden="true">
            <Kbd>Ctrl</Kbd>
            <Kbd>O</Kbd>
          </span>
        </button>

        {!api && (
          <div className="library__notice" role="alert">
            <Plug aria-hidden="true" />
            <span>Çeviri motoruna bağlanılamadı{engineError ? `: ${engineError}` : "."} Uygulamayı yeniden başlatmayı deneyin.</span>
          </div>
        )}
        {error && (
          <div className="library__notice">
            <WarningCircle aria-hidden="true" />
            <span>Kitaplık yüklenemedi: {error}</span>
          </div>
        )}

        {books === null && (
          <section className="shelf" aria-label="Son açılanlar yükleniyor">
            <h2 className="shelf__title">Son açılanlar</h2>
            <div className="shelf__grid">
              {[0, 1, 2].map((i) => (
                <div key={i} className="book-card">
                  <Skeleton className="cover" height="auto" />
                  <Skeleton width="70%" height={14} />
                  <Skeleton width="40%" />
                </div>
              ))}
            </div>
          </section>
        )}

        {books && books.length > 0 && (
          <section className="shelf" aria-label="Son açılanlar">
            <h2 className="shelf__title">Son açılanlar</h2>
            <ul className="shelf__grid">
              {books.map((b) => {
                const read = b.last_page ?? 0;
                return (
                  <li key={b.id}>
                    <button
                      type="button"
                      className={cx("book-card", !b.file_exists && "is-missing")}
                      onClick={() => onOpenPath(b.file_path)}
                      disabled={!b.file_exists || !api}
                      title={b.file_exists ? b.file_path : `Dosya bulunamadı: ${b.file_path}`}
                    >
                      <Cover api={api} bookId={b.id} title={b.title} />
                      <span className="book-card__title">{b.title}</span>
                      <span className="book-card__meta num">
                        {b.file_exists ? (
                          <>
                            {read > 0 ? `Sayfa ${read} / ${b.page_count}` : `${b.page_count} sayfa`}
                            {b.translated_pages > 0 && ` · ${percent(b.translated_pages, b.page_count)} çevrildi`}
                          </>
                        ) : (
                          "Dosya bulunamadı"
                        )}
                      </span>
                      {b.last_opened_at && <span className="book-card__when">{relativeTime(b.last_opened_at)}</span>}
                      <span className="book-card__bar" aria-hidden="true">
                        <span style={{ width: `${b.page_count ? Math.min(100, (read / b.page_count) * 100) : 0}%` }} />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {books && books.length === 0 && !error && api && (
          <p className="library__empty">Henüz açılmış bir kitap yok. İlk PDF'inizi açtığınızda burada görünecek.</p>
        )}
      </main>

      <footer className="library__foot">
        <span>
          Her yapay zekâ işlemi önce tahmini maliyeti gösterir ve onayınızı bekler. <Kbd>Ctrl</Kbd> <Kbd>K</Kbd> komutlar.
        </span>
      </footer>
    </div>
  );
}
