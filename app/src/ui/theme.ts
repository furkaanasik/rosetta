import { useCallback, useEffect, useState } from "react";

export type ThemePref = "system" | "light" | "dark";

const KEY = "rosetta.theme";

function read(): ThemePref {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : "system";
  } catch {
    return "system";
  }
}

/** Applies the theme to <html data-theme>; "system" follows prefers-color-scheme. */
export function applyTheme(pref: ThemePref = read()): void {
  const root = document.documentElement;
  if (pref === "system") delete root.dataset.theme;
  else root.dataset.theme = pref;
}

export function useTheme(): [ThemePref, (t: ThemePref) => void, () => void] {
  const [pref, setPref] = useState<ThemePref>(read);
  useEffect(() => applyTheme(pref), [pref]);
  const set = useCallback((t: ThemePref) => {
    try {
      localStorage.setItem(KEY, t);
    } catch {
      /* private mode: keep it for this session only */
    }
    setPref(t);
  }, []);
  const cycle = useCallback(() => set(pref === "system" ? "dark" : pref === "dark" ? "light" : "system"), [pref, set]);
  return [pref, set, cycle];
}

/** Small persisted boolean preference (UI-only, never sent anywhere). */
export function usePref(key: string, initial: boolean): [boolean, (v: boolean) => void] {
  const [v, setV] = useState<boolean>(() => {
    try {
      const s = localStorage.getItem(key);
      return s === null ? initial : s === "1";
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: boolean) => {
      try {
        localStorage.setItem(key, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      setV(next);
    },
    [key],
  );
  return [v, set];
}
