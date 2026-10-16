import { BookmarkSimple, Check, Sparkle, X } from "@phosphor-icons/react";
import { useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { LookupResult } from "../api/types";
import { Button, IconButton, Skeleton } from "../ui";

export interface LookupTarget {
  word: string;
  sentence: string;
  blockKey: string | null;
}

interface Props {
  api: EngineApi;
  target: LookupTarget;
  bookId: number | null;
  page: number;
  onClose: () => void;
  onSaved: () => void;
  onExplain: (text: string) => void;
}

/** Click a word → offline dictionary meaning, save to vocab, or ask the AI to explain (with confirmation). */
export function LookupPopover({ api, target, bookId, page, onClose, onSaved, onExplain }: Props) {
  const [result, setResult] = useState<LookupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .lookup(target.word)
      .then((r) => !cancelled && setResult(r))
      .catch((e: unknown) => !cancelled && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      cancelled = true;
    };
  }, [api, target.word]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.querySelector('[aria-modal="true"]')) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Save only once the lookup settled, so the stored meaning isn't empty by accident.
  const pending = !result && !error;

  const save = async (unknown: boolean) => {
    try {
      await api.addVocab({
        word: target.word,
        sentence: target.sentence,
        book_id: bookId ?? undefined,
        page,
        block_key: target.blockKey ?? undefined,
        meaning: result?.tr.join(", ") ?? "",
        unknown,
      });
      setSaved(true);
      onSaved();
    } catch (e) {
      setError(`Kaydedilemedi: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  const defs = result ? (showAll ? result.definitions.slice(0, 6) : result.definitions.slice(0, 2)) : [];
  const lemma = result && result.lemma !== target.word.toLowerCase() ? result.lemma : null;

  return (
    <div className="lookup" role="dialog" aria-label={`Sözlük: ${target.word}`}>
      <header className="lookup__head">
        <div>
          <p className="lookup__word">{target.word}</p>
          {lemma && <p className="lookup__lemma">kök: {lemma}</p>}
        </div>
        <IconButton label="Kapat" size="sm" onClick={onClose}>
          <X />
        </IconButton>
      </header>

      {error && <p className="error small">{error}</p>}
      {pending && (
        <div className="lookup__loading" aria-label="Aranıyor…">
          <Skeleton width="55%" height={18} />
          <Skeleton width="90%" />
        </div>
      )}
      {result && (
        <div className="lookup__body">
          {result.tr.length > 0 ? (
            <p className="tr lookup__tr">{result.tr.join(", ")}</p>
          ) : (
            <p className="muted small">Sözlükte Türkçe karşılık yok.</p>
          )}
          {defs.map((d, i) => (
            <p key={i} className="lookup__def">
              {d}
            </p>
          ))}
          {result.definitions.length > 2 && !showAll && (
            <button type="button" className="link-btn" onClick={() => setShowAll(true)}>
              daha fazla
            </button>
          )}
        </div>
      )}

      <footer className="lookup__actions">
        <Button
          variant="primary"
          size="sm"
          icon={saved ? <Check /> : <BookmarkSimple />}
          onClick={() => void save(true)}
          disabled={saved || pending}
        >
          {saved ? "Kaydedildi" : "Kaydet (bilmiyorum)"}
        </Button>
        <Button size="sm" variant="ghost" onClick={() => void save(false)} disabled={saved || pending}>
          Kaydet (biliyorum)
        </Button>
        {target.sentence && (
          <Button size="sm" variant="ghost" icon={<Sparkle />} onClick={() => onExplain(target.sentence)}>
            Bunu açıkla…
          </Button>
        )}
      </footer>
    </div>
  );
}
