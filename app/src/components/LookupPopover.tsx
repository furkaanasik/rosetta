import { useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { LookupResult } from "../api/types";

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

/** Click a word → offline dictionary meaning, save to vocab, or ask the AI to explain. */
export function LookupPopover({ api, target, bookId, page, onClose, onSaved, onExplain }: Props) {
  const [result, setResult] = useState<LookupResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

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

  // Save only once the lookup settled, so the stored meaning isn't empty by accident.
  const pending = !result && !error;

  const save = async (unknown: boolean) => {
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
  };

  return (
    <div className="popover" role="dialog" aria-label={`Sözlük: ${target.word}`}>
      <div className="popover-head">
        <strong>{target.word}</strong>
        {result && result.lemma !== target.word.toLowerCase() && <span className="muted"> → {result.lemma}</span>}
        <button type="button" className="close" onClick={onClose} aria-label="Kapat">
          ×
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {!result && !error && <p className="muted">Aranıyor…</p>}
      {result && (
        <>
          {result.tr.length > 0 ? <p className="tr">{result.tr.join(", ")}</p> : <p className="muted">Türkçe karşılık bulunamadı.</p>}
          {result.definitions.slice(0, 3).map((d, i) => (
            <p key={i} className="def">
              {d}
            </p>
          ))}
        </>
      )}
      <div className="popover-actions">
        <button type="button" onClick={() => void save(true)} disabled={saved || pending}>
          {saved ? "Kaydedildi" : "Kaydet (bilmiyorum)"}
        </button>
        <button type="button" onClick={() => void save(false)} disabled={saved || pending}>
          Kaydet (biliyorum)
        </button>
        {target.sentence && (
          <button type="button" onClick={() => onExplain(target.sentence)}>
            Bunu açıkla…
          </button>
        )}
      </div>
    </div>
  );
}
