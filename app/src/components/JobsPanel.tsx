import { useCallback, useEffect, useRef, useState } from "react";
import { useLatest } from "../lib/useLatest";
import type { EngineApi } from "../api/engine";
import type { Estimate, Job } from "../api/types";
import { stopReasonText, usd } from "../lib/format";
import { ArrowClockwise, Pause, Play, Plug, Stack, X } from "@phosphor-icons/react";
import { Badge, Button, EmptyState, Progress } from "../ui";
import { compressPages, percent, relativeTime } from "../ui/text";

const STATUS: Record<Job["status"], string> = {
  pending: "Bekliyor",
  running: "Çalışıyor",
  paused: "Duraklatıldı",
  done: "Bitti",
  failed: "Hatalı",
  cancelled: "İptal",
};

const TONE: Record<Job["status"], "neutral" | "accent" | "sage" | "amber" | "danger"> = {
  pending: "neutral",
  running: "accent",
  paused: "amber",
  done: "sage",
  failed: "danger",
  cancelled: "neutral",
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

  if (!api)
    return (
      <section className="panel" aria-label="Toplu işler">
        <EmptyState size="compact" icon={<Plug />} title="Motor bağlı değil" />
      </section>
    );

  return (
    <section className="panel" aria-label="Toplu işler">
      {jobs.length === 0 && (
        <EmptyState size="compact" icon={<Stack />} title="Henüz çeviri işi yok">
          Bir aralığı ya da tüm kitabı <strong>Çevir ▾</strong> menüsünden başlatın; ilerleme burada görünür.
        </EmptyState>
      )}
      {jobs.map((j) => {
        const total = j.pages.length || 1;
        const failed = Object.entries(j.failed_pages);
        const tone = TONE[j.status];
        return (
          <article key={j.id} className="job">
            <header className="job__head">
              <div className="job__title">
                <strong>Sayfa {compressPages(j.pages)}</strong>
                <span className="job__sub">
                  İş #{j.id}
                  {j.created_at && ` · ${relativeTime(j.created_at)}`}
                </span>
              </div>
              <Badge tone={tone}>{STATUS[j.status]}</Badge>
            </header>
            <Progress
              value={j.done_pages.length}
              max={total}
              label={`İlerleme ${percent(j.done_pages.length, total)}`}
              tone={j.status === "done" ? "sage" : j.status === "paused" ? "amber" : j.status === "failed" ? "danger" : "accent"}
              indeterminate={j.status === "pending"}
            />
            <p className="job__meta num">
              <span>
                {j.done_pages.length}/{j.pages.length} sayfa
              </span>
              <span>
                {usd(j.spent_usd)}
                {j.budget_usd !== null && <span className="muted"> / {usd(j.budget_usd)} bütçe</span>}
              </span>
            </p>
            {j.stop_reason && <p className="job__reason">{stopReasonText(j.stop_reason)}</p>}
            {failed.length > 0 && (
              <details className="job__failed">
                <summary>{failed.length} hatalı sayfa</summary>
                <ul>
                  {failed.map(([p, r]) => (
                    <li key={p}>
                      <span className="num">s.{p}</span> {r}
                    </li>
                  ))}
                </ul>
              </details>
            )}
            <div className="job__actions">
              {j.status === "running" && (
                <Button size="sm" icon={<Pause />} onClick={() => act(api.pauseJob(j.id))}>
                  Duraklat
                </Button>
              )}
              {j.status === "paused" && (
                <Button
                  size="sm"
                  variant="primary"
                  icon={<Play />}
                  onClick={() => requestConfirmed(() => api.estimateResumeJob(j.id), (t) => api.resumeJob(j.id, t), () => (watch(), void load()))}
                >
                  Devam
                </Button>
              )}
              {failed.length > 0 && !active(j) && (
                <Button
                  size="sm"
                  icon={<ArrowClockwise />}
                  onClick={() => requestConfirmed(() => api.estimateRetryFailed(j.id), (t) => api.retryFailed(j.id, t), () => (watch(), void load()))}
                >
                  Sadece hatalıları tekrar dene
                </Button>
              )}
              {(active(j) || j.status === "paused") && (
                <Button size="sm" variant="ghost" icon={<X />} onClick={() => act(api.cancelJob(j.id))}>
                  İptal
                </Button>
              )}
            </div>
          </article>
        );
      })}
    </section>
  );
}
