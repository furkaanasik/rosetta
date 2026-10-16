import { useEffect, useRef, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { BookProfile } from "../api/types";

const EMPTY: BookProfile = { tur: "", ton: "", hedef_dil: "tr", cevrilmeyecek: [], sozluk: {}, kod_dili: [] };

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  /** Starts "Kitabı Analiz Et"; `onDone` runs only after the user confirmed and it finished. */
  onAnalyze: (onDone: () => void) => void;
  onMessage: (m: string) => void;
}

/** Book profile editor: glossary table + do-not-translate chips. Editing never costs AI. */
export function ProfileEditor({ api, bookId, refreshKey, onAnalyze, onMessage }: Props) {
  const [profile, setProfile] = useState<BookProfile>(EMPTY);
  const [rows, setRows] = useState<[string, string][]>([]);
  const [chip, setChip] = useState("");
  const [loaded, setLoaded] = useState(false);

  // Unsaved edits; a (re)load must never overwrite them for the same book.
  const dirty = useRef(false);
  const loadedBook = useRef<number | null>(null);

  useEffect(() => {
    if (!api || bookId === null) return;
    let cancelled = false;
    api.getProfile(bookId).then(
      (p) => {
        if (cancelled || (dirty.current && loadedBook.current === bookId)) return;
        const prof = p ?? EMPTY;
        loadedBook.current = bookId;
        dirty.current = false;
        setProfile(prof);
        setRows(Object.entries(prof.sozluk));
        setLoaded(true);
      },
      (e: unknown) => {
        if (!cancelled) onMessage(`Profil yüklenemedi: ${e instanceof Error ? e.message : String(e)}`);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [api, bookId, refreshKey, onMessage]);

  if (!api || bookId === null) return <section className="panel"><p className="muted">Önce bir PDF açın.</p></section>;

  const edit = <T,>(set: (v: T) => void) => (v: T) => {
    dirty.current = true;
    set(v);
  };
  const editProfile = edit(setProfile);
  const editRows = edit(setRows);

  const save = async () => {
    const sozluk = Object.fromEntries(rows.filter(([k, v]) => k.trim() && v.trim()).map(([k, v]) => [k.trim(), v.trim()]));
    try {
      const saved = await api.putProfile(bookId, { ...profile, sozluk });
      dirty.current = false;
      setProfile(saved);
      onMessage("Profil kaydedildi (mevcut çeviriler değişmez; yeniden çeviri için --force).");
    } catch (e) {
      onMessage(`Profil kaydedilemedi: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  return (
    <section className="panel" aria-label="Kitap profili">
      <h3>Kitap profili</h3>
      {loaded && !profile.tur && <p className="muted">Profil yok. "Kitabı Analiz Et" ile oluşturabilir ya da elle doldurabilirsiniz.</p>}
      <button
        type="button"
        onClick={() =>
          // Unsaved edits are only given up once the analysis really ran (not on İptal).
          onAnalyze(() => {
            dirty.current = false;
          })
        }
      >
        Kitabı Analiz Et…
      </button>
      <label className="field">
        <span>Tür</span>
        <input value={profile.tur} onChange={(e) => editProfile({ ...profile, tur: e.target.value })} />
      </label>
      <label className="field">
        <span>Ton</span>
        <input value={profile.ton} onChange={(e) => editProfile({ ...profile, ton: e.target.value })} />
      </label>
      <h4>Sözlük</h4>
      <table className="glossary">
        <thead>
          <tr><th>İngilizce</th><th>Türkçe</th><th /></tr>
        </thead>
        <tbody>
          {rows.map(([k, v], i) => (
            <tr key={i}>
              <td><input aria-label="Terim" value={k} onChange={(e) => editRows(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} /></td>
              <td><input aria-label="Karşılık" value={v} onChange={(e) => editRows(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} /></td>
              <td><button type="button" aria-label="Sil" onClick={() => editRows(rows.filter((_, j) => j !== i))}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => editRows([...rows, ["", ""]])}>+ Terim</button>
      <h4>Çevrilmeyecek terimler</h4>
      <div className="chips">
        {profile.cevrilmeyecek.map((t) => (
          <span key={t} className="chip">
            {t}
            <button type="button" aria-label={`${t} kaldır`} onClick={() => editProfile({ ...profile, cevrilmeyecek: profile.cevrilmeyecek.filter((x) => x !== t) })}>×</button>
          </span>
        ))}
        <input
          aria-label="Yeni çevrilmeyecek terim"
          placeholder="ekle + Enter"
          value={chip}
          onChange={(e) => setChip(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && chip.trim() && !profile.cevrilmeyecek.includes(chip.trim())) {
              editProfile({ ...profile, cevrilmeyecek: [...profile.cevrilmeyecek, chip.trim()] });
              setChip("");
            }
          }}
        />
      </div>
      <button type="button" className="primary" onClick={() => void save()}>Kaydet</button>
    </section>
  );
}
