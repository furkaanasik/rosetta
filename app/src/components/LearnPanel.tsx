import { useCallback, useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { LearnStats, Rating, ReviewCard, TermInfo, VocabItem } from "../api/types";

type Tab = "vocab" | "review" | "terms" | "stats";

const RATINGS: { r: Rating; label: string }[] = [
  { r: "again", label: "Tekrar" },
  { r: "hard", label: "Zor" },
  { r: "good", label: "İyi" },
  { r: "easy", label: "Kolay" },
];

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  onChange: () => void;
}

export function LearnPanel({ api, bookId, refreshKey, onChange }: Props) {
  const [tab, setTab] = useState<Tab>("vocab");
  if (!api) return <section className="panel"><p className="muted">Motor bağlı değil.</p></section>;
  return (
    <section className="panel" aria-label="Öğrenme">
      <div className="tabs" role="tablist">
        {(["vocab", "review", "terms", "stats"] as Tab[]).map((t) => (
          <button key={t} type="button" role="tab" aria-selected={tab === t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {{ vocab: "Defter", review: "Tekrar", terms: "Terimler", stats: "İstatistik" }[t]}
          </button>
        ))}
      </div>
      {tab === "vocab" && <VocabList api={api} refreshKey={refreshKey} onChange={onChange} />}
      {tab === "review" && <Review api={api} onChange={onChange} />}
      {tab === "terms" && <Terms api={api} bookId={bookId} onChange={onChange} />}
      {tab === "stats" && <Stats api={api} refreshKey={refreshKey} />}
    </section>
  );
}

function VocabList({ api, refreshKey, onChange }: { api: EngineApi; refreshKey: number; onChange: () => void }) {
  const [items, setItems] = useState<VocabItem[]>([]);
  const [search, setSearch] = useState("");
  const load = useCallback(() => api.listVocab({ search: search || undefined }).then(setItems), [api, search]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);
  return (
    <>
      <input aria-label="Kelime ara" placeholder="Ara…" value={search} onChange={(e) => setSearch(e.target.value)} />
      {items.length === 0 && <p className="muted">Kelime defteri boş. Metinde bir kelimeye tıklayıp kaydedin.</p>}
      <ul className="vocab">
        {items.map((v) => (
          <li key={v.id}>
            <strong>{v.word}</strong> <span className="muted">{v.meaning}</span>
            <label className="small">
              <input
                type="checkbox"
                checked={v.unknown}
                onChange={(e) => void api.setUnknown(v.id, e.target.checked).then(() => (load(), onChange()))}
              />{" "}
              bilmiyorum
            </label>
          </li>
        ))}
      </ul>
    </>
  );
}

function Review({ api, onChange }: { api: EngineApi; onChange: () => void }) {
  const [cards, setCards] = useState<ReviewCard[] | null>(null);
  const [flipped, setFlipped] = useState(false);
  useEffect(() => {
    void api.dueCards(50).then(setCards);
  }, [api]);
  if (!cards) return <p className="muted">Yükleniyor…</p>;
  const card = cards[0];
  if (!card) return <p className="muted">Bugün tekrar edilecek kart yok. 🎉</p>;
  const rate = async (r: Rating) => {
    await api.review(card.vocab_id, r);
    setCards(cards.slice(1));
    setFlipped(false);
    onChange();
  };
  return (
    <div className="card">
      <p className="small muted">{cards.length} kart kaldı</p>
      <p className="cloze">{card.front}</p>
      {!flipped ? (
        <button type="button" className="primary" onClick={() => setFlipped(true)}>Cevabı göster</button>
      ) : (
        <>
          <p><strong>{card.word}</strong> — {card.meaning}</p>
          {card.sentence_tr && <p className="muted">{card.sentence_tr}</p>}
          <div className="row">
            {RATINGS.map(({ r, label }) => (
              <button key={r} type="button" onClick={() => void rate(r)}>{label}</button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Terms({ api, bookId, onChange }: { api: EngineApi; bookId: number | null; onChange: () => void }) {
  const [terms, setTerms] = useState<TermInfo[]>([]);
  const load = useCallback(() => (bookId === null ? Promise.resolve() : api.terms(bookId).then(setTerms)), [api, bookId]);
  useEffect(() => {
    void load();
  }, [load]);
  if (bookId === null) return <p className="muted">Önce bir PDF açın.</p>;
  return (
    <>
      {terms.length === 0 && <p className="muted">Profilde sözlük terimi yok.</p>}
      {terms.length > 0 && (
        <button type="button" onClick={() => void api.addTerms(bookId).then(() => (load(), onChange()))}>
          Tümünü deftere ekle
        </button>
      )}
      <ul className="vocab">
        {terms.map((t) => (
          <li key={t.term}>
            <strong>{t.term}</strong> <span className="muted">{t.tr}</span> {t.in_vocab && <span className="badge done">defterde</span>}
          </li>
        ))}
      </ul>
    </>
  );
}

function Stats({ api, refreshKey }: { api: EngineApi; refreshKey: number }) {
  const [s, setS] = useState<LearnStats | null>(null);
  useEffect(() => {
    void api.stats().then(setS);
  }, [api, refreshKey]);
  if (!s) return <p className="muted">Yükleniyor…</p>;
  return (
    <dl className="stats">
      <dt>Toplam kelime</dt><dd>{s.total_words}</dd>
      <dt>Öğrenilmiş</dt><dd>{s.mature_words}</dd>
      <dt>Bugün tekrar</dt><dd>{s.due_today}</dd>
      <dt>Bugün yapılan</dt><dd>{s.reviewed_today}</dd>
      <dt>Seri</dt><dd>{s.streak_days} gün</dd>
    </dl>
  );
}
