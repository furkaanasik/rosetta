import { ArrowsClockwise, CheckCircle, EyeSlash, Plug, PlusCircle } from "@phosphor-icons/react";
import { useCallback, useEffect, useState } from "react";
import { Badge, Button, EmptyState, SkeletonLines } from "../ui";
import { useLatest } from "../lib/useLatest";
import type { EngineApi } from "../api/engine";
import type { BlockRef, ConsistencyReport, TermIssue, TermVariant } from "../api/types";

/** Engine label of the "left in English" variant (quality/terms.py ENGLISH_LEFT). */
const ENGLISH_LEFT = "(İngilizce bırakılmış)";
/** Targeted re-translation: blocks per run (engine MAX_TARGET_BLOCKS). */
export const MAX_RETRANSLATE_BLOCKS = 200;

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  onGoto: (page: number) => void;
  /** Re-translates these blocks: estimate → CostModal → only runs after Onayla. */
  onRetranslate: (blocks: BlockRef[], term: string) => void;
  /** Called after the glossary changed (no AI). */
  onChanged: () => void;
  onMessage: (m: string) => void;
}

function message(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

/**
 * Term consistency of the book's existing translations. The analysis is local (never an AI);
 * "Sözlüğe ekle" only edits the profile; re-translation always goes through the cost estimate.
 */
export function ConsistencyPanel({ api, bookId, refreshKey, onGoto, onRetranslate, onChanged, onMessage }: Props) {
  const [report, setReport] = useState<ConsistencyReport | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busyTerm, setBusyTerm] = useState<string | null>(null);
  const latest = useLatest();

  const load = useCallback(() => {
    if (!api || bookId === null) return Promise.resolve();
    setErr(null);
    return latest(api.consistency(bookId), setReport, (e) => setErr(message(e)));
  }, [api, bookId, latest]);

  useEffect(() => {
    setReport(null);
  }, [bookId]);
  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  if (!api || bookId === null)
    return (
      <section className="panel" aria-label="Tutarlılık">
        <EmptyState size="compact" icon={<Plug />} title={api ? "Önce bir PDF açın" : "Motor bağlı değil"} />
      </section>
    );

  const accept = async (issue: TermIssue, variant: TermVariant) => {
    const tr = variant.key === ENGLISH_LEFT ? issue.term : variant.label;
    setBusyTerm(issue.term);
    try {
      const res = await api.acceptTerm(bookId, issue.term, tr);
      const rest = res.affected_count ? ` · ${res.affected_count} paragraf farklı karşılık kullanıyor` : "";
      onMessage(`Sözlüğe eklendi: ${issue.term} → ${tr}${rest}`);
      onChanged();
    } catch (e) {
      setErr(`Sözlüğe eklenemedi: ${message(e)}`);
    } finally {
      setBusyTerm(null);
    }
  };

  const ignore = async (term: string, undo = false) => {
    try {
      await (undo ? api.unignoreTerm(bookId, term) : api.ignoreTerm(bookId, term));
      await load();
    } catch (e) {
      setErr(message(e));
    }
  };

  const retranslate = (issue: TermIssue) => {
    const seen = new Set<string>();
    const blocks: BlockRef[] = [];
    for (const a of issue.affected) {
      const key = `${a.page}:${a.text_hash}`;
      if (seen.has(key)) continue;
      seen.add(key);
      blocks.push({ page: a.page, text_hash: a.text_hash });
    }
    onRetranslate(blocks.slice(0, MAX_RETRANSLATE_BLOCKS), issue.term);
  };

  const glossary = report?.issues.filter((i) => i.source === "glossary") ?? [];
  const mined = report?.issues.filter((i) => i.source === "mined") ?? [];
  const card = (i: TermIssue) => (
    <IssueCard
      key={i.term}
      issue={i}
      busy={busyTerm === i.term}
      onAccept={(v) => void accept(i, v)}
      onIgnore={() => void ignore(i.term)}
      onRetranslate={() => retranslate(i)}
      onGoto={onGoto}
    />
  );

  return (
    <section className="panel consistency" aria-label="Tutarlılık">
      <div className="consistency__intro">
        <p className="muted small">
          Mevcut çeviriler yerel olarak taranır (yapay zekâ kullanılmaz). Sonuçlar <em>olası</em> tutarsızlıklardır; örneklere
          bakarak karar verin.
        </p>
        <Button size="sm" variant="ghost" icon={<ArrowsClockwise />} onClick={() => void load()}>
          Yenile
        </Button>
      </div>
      {err && <p className="error small">{err}</p>}
      {report === null && !err && <SkeletonLines lines={5} />}
      {report !== null && report.analyzed_blocks === 0 && (
        <EmptyState size="compact" title="Henüz çevrilmiş sayfa yok">
          Önce birkaç sayfa çevirin; tutarlılık mevcut çeviriler üzerinden denetlenir.
        </EmptyState>
      )}
      {report !== null && report.analyzed_blocks > 0 && (
        <>
          <p className="consistency__summary small" role="status">
            {report.issues.length
              ? `${report.issues.length} olası tutarsızlık · ${report.analyzed_blocks} çevrilmiş paragraf tarandı`
              : `Tutarsızlık bulunmadı · ${report.analyzed_blocks} paragraf tarandı`}
          </p>
          {report.issues.length === 0 && <EmptyState size="compact" icon={<CheckCircle />} title="Terimler tutarlı görünüyor" />}
          {glossary.length > 0 && (
            <>
              <h4 className="panel__heading">
                Sözlük terimleri <span className="muted num">{glossary.length}</span>
              </h4>
              <div className="consistency__list">{glossary.map(card)}</div>
            </>
          )}
          {mined.length > 0 && (
            <>
              <h4 className="panel__heading">
                Keşfedilen terimler <span className="muted num">{mined.length}</span>
              </h4>
              <div className="consistency__list">{mined.map(card)}</div>
            </>
          )}
        </>
      )}
      {report !== null && report.ignored.length > 0 && (
        <p className="consistency__ignored small muted">
          Yok sayılanlar:{" "}
          {report.ignored.map((t) => (
            <button key={t} type="button" className="chip" onClick={() => void ignore(t, true)} title="Yeniden denetle">
              {t} ↺
            </button>
          ))}
        </p>
      )}
    </section>
  );
}

interface CardProps {
  issue: TermIssue;
  busy: boolean;
  onAccept: (v: TermVariant) => void;
  onIgnore: () => void;
  onRetranslate: () => void;
  onGoto: (page: number) => void;
}

function IssueCard({ issue, busy, onAccept, onIgnore, onRetranslate, onGoto }: CardProps) {
  const total = issue.affected_count;
  return (
    <article className="term-issue" aria-label={issue.term}>
      <header className="term-issue__head">
        <strong className="term-issue__term">{issue.term}</strong>
        {issue.preferred !== null ? (
          <span className="term-issue__sub">
            sözlük: “{issue.preferred}”{total > 0 && <> · <Badge tone="amber">{total} uyumsuz</Badge></>}
          </span>
        ) : (
          <span className="term-issue__sub muted">sözlükte yok · {issue.occurrences} geçiş</span>
        )}
      </header>
      <ul className="term-issue__variants">
        {issue.variants.map((v) => {
          const chosen = issue.preferred !== null && v.label === issue.preferred;
          return (
            <li key={v.key} className="term-variant">
              <div className="term-variant__row">
                <span className="term-variant__label">{v.label}</span>
                <span className="muted num">×{v.count}</span>
                {chosen ? (
                  <Badge tone="sage">sözlükte</Badge>
                ) : (
                  <Button size="sm" variant="ghost" icon={<PlusCircle />} disabled={busy} onClick={() => onAccept(v)}>
                    Sözlüğe ekle
                  </Button>
                )}
              </div>
              {v.examples.length > 0 && (
                <details className="term-variant__examples">
                  <summary>Örnekler</summary>
                  <ul>
                    {v.examples.map((ex, n) => (
                      <li key={n}>
                        <button type="button" className="term-example__page" onClick={() => onGoto(ex.page)}>
                          s. {ex.page}
                        </button>
                        <span className="term-example__en">{ex.en}</span>
                        <span className="term-example__tr">{ex.tr}</span>
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </li>
          );
        })}
      </ul>
      <div className="term-issue__actions">
        {total > 0 && (
          <Button size="sm" icon={<ArrowsClockwise />} onClick={onRetranslate}>
            {total > MAX_RETRANSLATE_BLOCKS
              ? `İlk ${MAX_RETRANSLATE_BLOCKS} uyumsuz paragrafı yeniden çevir…`
              : `Uyumsuz ${total} paragrafı yeniden çevir…`}
          </Button>
        )}
        <Button size="sm" variant="ghost" icon={<EyeSlash />} onClick={onIgnore}>
          Yok say
        </Button>
      </div>
    </article>
  );
}
