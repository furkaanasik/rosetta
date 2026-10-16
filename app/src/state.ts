import type { BookInfo, ViewMode } from "./api/types";

export type SidePanel = "control" | "jobs" | "profile" | "learn";

export interface AppState {
  book: BookInfo | null;
  pdfSrc: string | null;
  page: number;
  zoom: number;
  mode: ViewMode;
  tocOpen: boolean;
  panel: SidePanel;
  /** Bumped after translations change so views refetch. */
  revision: number;
}

export type Action =
  | { type: "bookOpened"; book: BookInfo; pdfSrc: string | null }
  | { type: "goto"; page: number }
  | { type: "zoom"; zoom: number }
  | { type: "mode"; mode: ViewMode }
  | { type: "toggleToc" }
  | { type: "panel"; panel: SidePanel }
  | { type: "refresh" };

export const initialState: AppState = {
  book: null,
  pdfSrc: null,
  page: 1,
  zoom: 1.25,
  mode: "split",
  tocOpen: true,
  panel: "control",
  revision: 0,
};

export const MIN_ZOOM = 0.5;
export const MAX_ZOOM = 3;

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "bookOpened":
      return { ...state, book: action.book, pdfSrc: action.pdfSrc, page: 1, revision: state.revision + 1 };
    case "goto": {
      const max = state.book?.page_count ?? 1;
      return { ...state, page: Math.min(max, Math.max(1, Math.round(action.page))) };
    }
    case "zoom":
      return { ...state, zoom: Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, action.zoom)) };
    case "mode":
      return { ...state, mode: action.mode };
    case "toggleToc":
      return { ...state, tocOpen: !state.tocOpen };
    case "panel":
      return { ...state, panel: action.panel };
    case "refresh":
      return { ...state, revision: state.revision + 1 };
  }
}

export const MODE_LABELS: Record<ViewMode, string> = {
  original: "Orijinal",
  split: "Split",
  translation: "Sadece Çeviri",
  learn: "Öğrenme",
};
