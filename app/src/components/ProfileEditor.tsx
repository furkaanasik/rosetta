import { useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { BookProfile } from "../api/types";

const EMPTY: BookProfile = { tur: "", ton: "", hedef_dil: "tr", cevrilmeyecek: [], sozluk: {}, kod_dili: [] };

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  onAnalyze: () => void;
  onMessage: (m: string) => void;
}

/** Book profile editor: glossary table + do-not-translate chips. Editing never costs AI. */
export function ProfileEditor({ api, bookId, refreshKey, onAnalyze, onMessage }: Props) {
  const [profile, setProfile] = useState<BookProfile>(EMPTY);
  const [rows, setRows] = useState<[string, string][]>([]);
  const [chip, setChip] = useState("");
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!api || bookId === null) return;
    api.getProfile(bookId).then((p) => {
      const prof = p ?? EMPTY;
      setProfile(prof);
      setRows(Object.entries(prof.sozluk));
      setLoaded(true);
    });
  }, [api, bookId, refreshKey]);

  if (!api || bookId === null) return <section className="panel"><p className="muted">Önce bir PDF açın.</p></section>;

  const save = async () => {
    const sozluk = Object.fromEntries(rows.filter(([k, v]) => k.trim() && v.trim()).map(([k, v]) => [k.trim(), v.trim()]));
    const saved = await api.putProfile(bookId, { ...profile, sozluk });
    setProfile(saved);
    onMessage("Profil kaydedildi (mevcut çeviriler değişmez; yeniden çeviri için --force).");
  };

  return (
    <section className="panel" aria-label="Kitap profili">
      <h3>Kitap profili</h3>
      {loaded && !profile.tur && <p className="muted">Profil yok. "Kitabı Analiz Et" ile oluşturabilir ya da elle doldurabilirsiniz.</p>}
      <button type="button" onClick={onAnalyze}>Kitabı Analiz Et…</button>
      <label className="field">
        <span>Tür</span>
        <input value={profile.tur} onChange={(e) => setProfile({ ...profile, tur: e.target.value })} />
      </label>
      <label className="field">
        <span>Ton</span>
        <input value={profile.ton} onChange={(e) => setProfile({ ...profile, ton: e.target.value })} />
      </label>
      <h4>Sözlük</h4>
      <table className="glossary">
        <thead>
          <tr><th>İngilizce</th><th>Türkçe</th><th /></tr>
        </thead>
        <tbody>
          {rows.map(([k, v], i) => (
            <tr key={i}>
              <td><input aria-label="Terim" value={k} onChange={(e) => setRows(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} /></td>
              <td><input aria-label="Karşılık" value={v} onChange={(e) => setRows(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} /></td>
              <td><button type="button" aria-label="Sil" onClick={() => setRows(rows.filter((_, j) => j !== i))}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button type="button" onClick={() => setRows([...rows, ["", ""]])}>+ Terim</button>
      <h4>Çevrilmeyecek terimler</h4>
      <div className="chips">
        {profile.cevrilmeyecek.map((t) => (
          <span key={t} className="chip">
            {t}
            <button type="button" aria-label={`${t} kaldır`} onClick={() => setProfile({ ...profile, cevrilmeyecek: profile.cevrilmeyecek.filter((x) => x !== t) })}>×</button>
          </span>
        ))}
        <input
          aria-label="Yeni çevrilmeyecek terim"
          placeholder="ekle + Enter"
          value={chip}
          onChange={(e) => setChip(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && chip.trim() && !profile.cevrilmeyecek.includes(chip.trim())) {
              setProfile({ ...profile, cevrilmeyecek: [...profile.cevrilmeyecek, chip.trim()] });
              setChip("");
            }
          }}
        />
      </div>
      <button type="button" className="primary" onClick={() => void save()}>Kaydet</button>
    </section>
  );
}
