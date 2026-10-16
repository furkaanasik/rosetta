import type { BookInfo, ViewMode } from "./api/types";

export type Screen = "library" | "reader";
export type SidePanel = "toc" | "jobs" | "words" | "profile";

export interface AppState {
  screen: Screen;
  book: BookInfo | null;
  pdfSrc: string | null;
  page: number;
  zoom: number;
  mode: ViewMode;
  /** Slide-over side panel (closed by default: the page gets the room). */
  panelOpen: boolean;
  panel: SidePanel;
  /** Bumped after translations change so views refetch. */
  revision: number;
  /** Fit the page width to the reading area (default); any explicit zoom turns it off. */
  fit: boolean;
}

export type Action =
  | { type: "bookOpened"; book: BookInfo; pdfSrc: string | null; page?: number }
  | { type: "goto"; page: number }
  | { type: "zoom"; zoom: number }
  | { type: "fit" }
  | { type: "mode"; mode: ViewMode }
  | { type: "panel"; panel: SidePanel }
  | { type: "togglePanel"; panel?: SidePanel }
  | { type: "closePanel" }
  | { type: "library" }
  | { type: "refresh" };

export const MIN_ZOOM = 0.5;
export const MAX_ZOOM = 3;

export const initialState: AppState = {
  screen: "library",
  book: null,
  pdfSrc: null,
  page: 1,
  zoom: 1,
  mode: "split",
  panelOpen: false,
  panel: "toc",
  revision: 0,
  fit: true,
};

const clampPage = (page: number, book: BookInfo | null) =>
  Math.min(book?.page_count ?? 1, Math.max(1, Math.round(Number.isFinite(page) ? page : 1)));

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "bookOpened":
      return {
        ...state,
        screen: "reader",
        book: action.book,
        pdfSrc: action.pdfSrc,
        page: clampPage(action.page ?? 1, action.book),
        revision: state.revision + 1,
      };
    case "goto":
      return { ...state, page: clampPage(action.page, state.book) };
    case "zoom":
      return { ...state, fit: false, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(action.zoom * 100) / 100)) };
    case "fit":
      return { ...state, fit: true };
    case "mode":
      return { ...state, mode: action.mode };
    case "panel":
      return { ...state, panel: action.panel, panelOpen: true };
    case "togglePanel": {
      const panel = action.panel ?? state.panel;
      const open = !(state.panelOpen && panel === state.panel);
      return { ...state, panel, panelOpen: open };
    }
    case "closePanel":
      return { ...state, panelOpen: false };
    case "library":
      return { ...state, screen: "library", panelOpen: false };
    case "refresh":
      return { ...state, revision: state.revision + 1 };
  }
}

export const MODE_LABELS: Record<ViewMode, string> = {
  original: "Orijinal",
  split: "Yan yana",
  translation: "Türkçe",
  learn: "Öğrenme",
};

export const PANEL_LABELS: Record<SidePanel, string> = {
  toc: "İçindekiler",
  jobs: "İşler",
  words: "Kelimeler",
  profile: "Profil",
};
