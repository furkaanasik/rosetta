import { BookOpenText, Cards, CheckCircle, MagnifyingGlass, Plug, PlusCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, EmptyState, Segmented, SkeletonLines } from "../ui";
import { useLatest } from "../lib/useLatest";
import type { EngineApi } from "../api/engine";
import type { LearnStats, Rating, ReviewCard, TermInfo, VocabItem } from "../api/types";

type Tab = "vocab" | "review" | "terms" | "stats";

const RATINGS: { r: Rating; label: string }[] = [
  { r: "again", label: "Tekrar" },
  { r: "hard", label: "Zor" },
  { r: "good", label: "İyi" },
  { r: "easy", label: "Kolay" },
];

/** Small inline error line for one sub-panel; `report` is a ready-made rejection handler. */
function useErrorLine(): [string | null, (e: unknown) => void] {
  const [err, setErr] = useState<string | null>(null);
  const report = useCallback((e: unknown) => setErr(e instanceof Error ? e.message : String(e)), []);
  return [err, report];
}

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  onChange: () => void;
}

export function LearnPanel({ api, bookId, refreshKey, onChange }: Props) {
  const [tab, setTab] = useState<Tab>("vocab");
  if (!api)
    return (
      <section className="panel" aria-label="Öğrenme">
        <EmptyState size="compact" icon={<Plug />} title="Motor bağlı değil" />
      </section>
    );
  return (
    <section className="panel" aria-label="Öğrenme">
      <Segmented<Tab>
        label="Öğrenme bölümleri"
        value={tab}
        onChange={setTab}
        className="segmented--full"
        items={[
          { value: "vocab", label: "Defter" },
          { value: "review", label: "Tekrar" },
          { value: "terms", label: "Terimler" },
          { value: "stats", label: "İstatistik" },
        ]}
      />
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
  const latest = useLatest();
  const [err, report] = useErrorLine();
  const load = useCallback(() => latest(api.listVocab({ search: search || undefined }), setItems, report), [api, search, latest, report]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);
  return (
    <>
      {err && <p className="error small">{err}</p>}
      <label className="search">
        <MagnifyingGlass aria-hidden="true" />
        <input aria-label="Kelime ara" placeholder="Defterde ara…" value={search} onChange={(e) => setSearch(e.target.value)} />
      </label>
      {items.length === 0 && (
        <EmptyState size="compact" icon={<BookOpenText />} title={search ? "Eşleşen kelime yok" : "Kelime defteri boş"}>
          {!search && "Metinde bir kelimeye tıklayıp kaydedin."}
        </EmptyState>
      )}
      <ul className="vocab">
        {items.map((v) => (
          <li key={v.id} className="vocab__item">
            <div className="vocab__text">
              <strong className="vocab__word">{v.word}</strong>
              <span className="vocab__meaning">{v.meaning || "—"}</span>
            </div>
            <label className="vocab__toggle" title="İşaretli kelimelerin karşılığı Öğrenme görünümünde gösterilir">
              <input
                type="checkbox"
                checked={v.unknown}
                onChange={(e) => void api.setUnknown(v.id, e.target.checked).then(() => (load(), onChange()), report)}
              />
              <span>bilmiyorum</span>
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
  const latest = useLatest();
  const [err, report] = useErrorLine();
  useEffect(() => {
    void latest(api.dueCards(50), setCards, report);
  }, [api, latest, report]);
  if (!cards) return err ? <p className="error small">{err}</p> : <SkeletonLines lines={3} />;
  const card = cards[0];
  if (!card)
    return (
      <EmptyState size="compact" icon={<CheckCircle />} title="Bugünlük bu kadar">
        Tekrar edilecek kart yok.
      </EmptyState>
    );
  const rate = async (r: Rating) => {
    try {
      await api.review(card.vocab_id, r);
      setCards(cards.slice(1));
      setFlipped(false);
      onChange();
    } catch (e) {
      report(e);
    }
  };
  return (
    <div className="card flashcard">
      {err && <p className="error small">{err}</p>}
      <p className="flashcard__count num">
        <Cards aria-hidden="true" /> {cards.length} kart kaldı
      </p>
      <p className="cloze">{card.front}</p>
      {!flipped ? (
        <Button variant="primary" onClick={() => setFlipped(true)}>
          Cevabı göster
        </Button>
      ) : (
        <>
          <div className="flashcard__back">
            <p className="flashcard__word">
              <strong>{card.word}</strong> <span>{card.meaning}</span>
            </p>
            {card.sentence_tr && <p className="flashcard__tr">{card.sentence_tr}</p>}
          </div>
          <div className="flashcard__ratings">
            {RATINGS.map(({ r, label }) => (
              <Button key={r} size="sm" className={`rate rate--${r}`} onClick={() => void rate(r)}>
                {label}
              </Button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function Terms({ api, bookId, onChange }: { api: EngineApi; bookId: number | null; onChange: () => void }) {
  const [terms, setTerms] = useState<TermInfo[]>([]);
  const latest = useLatest();
  const [err, report] = useErrorLine();
  const load = useCallback(
    () => (bookId === null ? latest(Promise.resolve([]), setTerms) : latest(api.terms(bookId), setTerms, report)),
    [api, bookId, latest, report],
  );
  useEffect(() => {
    void load();
  }, [load]);
  if (bookId === null) return <EmptyState size="compact" title="Önce bir PDF açın" />;
  return (
    <>
      {err && <p className="error small">{err}</p>}
      {terms.length === 0 && (
        <EmptyState size="compact" icon={<BookOpenText />} title="Profilde sözlük terimi yok">
          Kitap profili oluşturulunca teknik terimler burada listelenir.
        </EmptyState>
      )}
      {terms.length > 0 && (
        <Button size="sm" icon={<PlusCircle />} onClick={() => void api.addTerms(bookId).then(() => (load(), onChange()), report)}>
          Tümünü deftere ekle
        </Button>
      )}
      <ul className="vocab">
        {terms.map((t) => (
          <li key={t.term} className="vocab__item">
            <div className="vocab__text">
              <strong className="vocab__word">{t.term}</strong>
              <span className="vocab__meaning">{t.tr}</span>
            </div>
            {t.in_vocab && <Badge tone="sage">defterde</Badge>}
          </li>
        ))}
      </ul>
    </>
  );
}

function Stats({ api, refreshKey }: { api: EngineApi; refreshKey: number }) {
  const [s, setS] = useState<LearnStats | null>(null);
  const latest = useLatest();
  const [err, report] = useErrorLine();
  useEffect(() => {
    void latest(api.stats(), setS, report);
  }, [api, refreshKey, latest, report]);
  if (!s) return err ? <p className="error small">{err}</p> : <SkeletonLines lines={3} />;
  return (
    <dl className="stats num">
      <div className="stat">
        <dt>Toplam kelime</dt>
        <dd>{s.total_words}</dd>
      </div>
      <div className="stat">
        <dt>Öğrenilmiş</dt>
        <dd>{s.mature_words}</dd>
      </div>
      <div className="stat">
        <dt>Bugün tekrar</dt>
        <dd>{s.due_today}</dd>
      </div>
      <div className="stat">
        <dt>Bugün yapılan</dt>
        <dd>{s.reviewed_today}</dd>
      </div>
      <div className="stat stat--wide">
        <dt>Seri</dt>
        <dd>{s.streak_days} gün</dd>
      </div>
    </dl>
  );
}
