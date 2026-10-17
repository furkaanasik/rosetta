import { MagicWand, Plus, Trash, X } from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";
import { Button, EmptyState, IconButton } from "../ui";
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
  // Glossary as last loaded/saved: terms added elsewhere since (Tutarlılık → "Sözlüğe ekle")
  // are merged in on save instead of being silently dropped by this full-profile PUT.
  const baseline = useRef<Record<string, string>>({});

  useEffect(() => {
    if (!api || bookId === null) return;
    let cancelled = false;
    api.getProfile(bookId).then(
      (p) => {
        if (cancelled || (dirty.current && loadedBook.current === bookId)) return;
        const prof = p ?? EMPTY;
        loadedBook.current = bookId;
        dirty.current = false;
        baseline.current = prof.sozluk;
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

  if (!api || bookId === null)
    return (
      <section className="panel" aria-label="Kitap profili">
        <EmptyState size="compact" title="Önce bir PDF açın" />
      </section>
    );

  const edit = <T,>(set: (v: T) => void) => (v: T) => {
    dirty.current = true;
    set(v);
  };
  const editProfile = edit(setProfile);
  const editRows = edit(setRows);

  const save = async () => {
    const sozluk = Object.fromEntries(rows.filter(([k, v]) => k.trim() && v.trim()).map(([k, v]) => [k.trim(), v.trim()]));
    try {
      const server = await api.getProfile(bookId);
      for (const [k, v] of Object.entries(server?.sozluk ?? {})) {
        // Added on the server since this editor loaded, and not deleted/edited here.
        if (!(k in baseline.current) && !(k in sozluk)) sozluk[k] = v;
      }
      const saved = await api.putProfile(bookId, { ...profile, sozluk });
      dirty.current = false;
      baseline.current = saved.sozluk;
      setProfile(saved);
      setRows(Object.entries(saved.sozluk));
      onMessage("Profil kaydedildi. Mevcut çeviriler değişmez.");
    } catch (e) {
      onMessage(`Profil kaydedilemedi: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const addChip = () => {
    const t = chip.trim();
    if (t && !profile.cevrilmeyecek.includes(t)) editProfile({ ...profile, cevrilmeyecek: [...profile.cevrilmeyecek, t] });
    setChip("");
  };

  return (
    <section className="panel profile" aria-label="Kitap profili">
      <div className="profile__intro">
        <p className="muted small">
          Profil çevirinin tutarlılığı içindir: terimler kitap boyunca aynı karşılıkla çevrilir. Düzenlemek ücretsizdir; mevcut
          çeviriler değişmez.
        </p>
        <Button
          size="sm"
          icon={<MagicWand />}
          onClick={() =>
            // Unsaved edits are only given up once the analysis really ran (not on İptal).
            onAnalyze(() => {
              dirty.current = false;
            })
          }
        >
          Kitabı analiz et…
        </Button>
      </div>
      {loaded && !profile.tur && <p className="profile__hint">Henüz profil yok: analizle oluşturabilir ya da elle doldurabilirsiniz.</p>}

      <div className="profile__grid">
        <label className="field">
          <span>Tür</span>
          <input value={profile.tur} placeholder="ör. yazılım / dağıtık sistemler" onChange={(e) => editProfile({ ...profile, tur: e.target.value })} />
        </label>
        <label className="field">
          <span>Ton</span>
          <input value={profile.ton} placeholder="ör. teknik ama akıcı" onChange={(e) => editProfile({ ...profile, ton: e.target.value })} />
        </label>
      </div>

      <h4 className="panel__heading">
        Sözlük <span className="muted num">{rows.length}</span>
      </h4>
      <div className="glossary" role="table" aria-label="Sözlük">
        <div className="glossary__row glossary__row--head" role="row">
          <span role="columnheader">İngilizce</span>
          <span role="columnheader">Türkçe</span>
          <span role="columnheader" className="visually-hidden">
            Sil
          </span>
        </div>
        {rows.map(([k, v], i) => (
          <div className="glossary__row" role="row" key={i}>
            <input aria-label="Terim" value={k} onChange={(e) => editRows(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
            <input aria-label="Karşılık" value={v} onChange={(e) => editRows(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} />
            <IconButton label="Sil" size="sm" onClick={() => editRows(rows.filter((_, j) => j !== i))}>
              <Trash />
            </IconButton>
          </div>
        ))}
      </div>
      <Button size="sm" variant="ghost" icon={<Plus />} onClick={() => editRows([...rows, ["", ""]])}>
        Terim ekle
      </Button>

      <h4 className="panel__heading">Çevrilmeyecek terimler</h4>
      <div className="chips">
        {profile.cevrilmeyecek.map((t) => (
          <span key={t} className="chip">
            {t}
            <button type="button" aria-label={`${t} kaldır`} onClick={() => editProfile({ ...profile, cevrilmeyecek: profile.cevrilmeyecek.filter((x) => x !== t) })}>
              <X aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          className="chip-input"
          aria-label="Yeni çevrilmeyecek terim"
          placeholder="Ekle ve Enter'a bas"
          value={chip}
          onChange={(e) => setChip(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") addChip();
          }}
        />
      </div>
      <div className="panel__footer">
        <Button variant="primary" onClick={() => void save()}>
          Kaydet
        </Button>
      </div>
    </section>
  );
}
