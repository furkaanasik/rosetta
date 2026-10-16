import { useCallback, useEffect, useRef, useState } from "react";
import { useLatest } from "../lib/useLatest";
import type { EngineApi } from "../api/engine";
import type { Estimate, Job } from "../api/types";
import { stopReasonText, usd } from "../lib/format";

const STATUS: Record<Job["status"], string> = {
  pending: "Bekliyor",
  running: "Çalışıyor",
  paused: "Duraklatıldı",
  done: "Bitti",
  failed: "Hatalı",
  cancelled: "İptal",
};

const POLL_MS = 1500;
/** After start/resume/retry the job may still read "paused"/"pending" for a moment. */
const WATCH_MS = 15000;

const active = (j: Job) => j.status === "pending" || j.status === "running";

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  requestConfirmed: <T>(est: () => Promise<Estimate>, run: (t: string) => Promise<T>, done?: (r: T) => void) => void;
  /** Pages a job finished since the last poll (1-based) and whether any job just stopped. */
  onProgress: (donePages: number[], stopped: boolean) => void;
  onError: (e: unknown) => void;
}

export function JobsPanel({ api, bookId, refreshKey, requestConfirmed, onProgress, onError }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);
  // Short polling window after start/resume/retry, until the job leaves "paused"/"pending".
  const [watching, setWatching] = useState(false);
  const watchTimer = useRef<number | undefined>(undefined);
  const seen = useRef<Map<number, { done: Set<number>; active: boolean }> | null>(null);
  const latest = useLatest();

  const apply = useCallback(
    (list: Job[]) => {
      const prev = seen.current;
      const next = new Map<number, { done: Set<number>; active: boolean }>();
      const newly: number[] = [];
      let stopped = false;
      for (const j of list) {
        const before = prev?.get(j.id);
        next.set(j.id, { done: new Set(j.done_pages), active: active(j) });
        if (!prev) continue; // first load: nothing "new" yet
        for (const p of j.done_pages) if (!before?.done.has(p)) newly.push(p);
        if (before?.active && !active(j)) stopped = true;
      }
      seen.current = next;
      setJobs(list);
      if (newly.length || stopped) onProgress(newly, stopped);
    },
    [onProgress],
  );

  const load = useCallback(async () => {
    if (!api) return;
    const fetchJobs = async () => {
      const list = await api.listJobs(bookId ?? undefined);
      return Promise.all(list.map((j) => (active(j) ? api.getJob(j.id) : j)));
    };
    await latest(fetchJobs(), apply, onError);
  }, [api, bookId, latest, apply, onError]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  const polling = watching || jobs.some(active);
  useEffect(() => {
    if (!polling) return;
    const t = window.setInterval(() => void load(), POLL_MS);
    return () => window.clearInterval(t);
  }, [polling, load]);
  useEffect(() => () => window.clearTimeout(watchTimer.current), []);

  const watch = () => {
    setWatching(true);
    window.clearTimeout(watchTimer.current);
    watchTimer.current = window.setTimeout(() => setWatching(false), WATCH_MS);
  };
  const act = (p: Promise<unknown>) => void p.then(load, onError);

  if (!api) return <section className="panel"><p className="muted">Motor bağlı değil.</p></section>;

  return (
    <section className="panel" aria-label="Toplu işler">
      <h3>Toplu işler</h3>
      {jobs.length === 0 && <p className="muted">İş yok. "Aralık Çevir" veya "Tüm Kitabı Çevir" ile başlatın.</p>}
      {jobs.map((j) => {
        const total = j.pages.length || 1;
        const pct = Math.round((j.done_pages.length / total) * 100);
        const failed = Object.entries(j.failed_pages);
        return (
          <article key={j.id} className="job">
            <header>
              <strong>İş #{j.id}</strong> <span className={`badge ${j.status}`}>{STATUS[j.status]}</span>
            </header>
            <progress max={total} value={j.done_pages.length} aria-label={`İlerleme %${pct}`} />
            <p className="small">
              {j.done_pages.length}/{j.pages.length} sayfa · harcanan {usd(j.spent_usd)}
              {j.budget_usd !== null && ` / bütçe ${usd(j.budget_usd)}`}
            </p>
            {j.stop_reason && <p className="small warn">{stopReasonText(j.stop_reason)}</p>}
            {failed.length > 0 && (
              <details>
                <summary>{failed.length} hatalı sayfa</summary>
                <ul className="small">
                  {failed.map(([p, r]) => (
                    <li key={p}>
                      s.{p}: {r}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <div className="row">
              {j.status === "running" && (
                <button type="button" onClick={() => act(api.pauseJob(j.id))}>
                  Duraklat
                </button>
              )}
              {j.status === "paused" && (
                <button type="button" onClick={() => requestConfirmed(() => api.estimateResumeJob(j.id), (t) => api.resumeJob(j.id, t), () => (watch(), void load()))}>
                  Devam
                </button>
              )}
              {failed.length > 0 && !active(j) && (
                <button type="button" onClick={() => requestConfirmed(() => api.estimateRetryFailed(j.id), (t) => api.retryFailed(j.id, t), () => (watch(), void load()))}>
                  Sadece hatalıları tekrar dene
                </button>
              )}
              {(active(j) || j.status === "paused") && (
                <button type="button" onClick={() => act(api.cancelJob(j.id))}>
                  İptal
                </button>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}
