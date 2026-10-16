import { useCallback, useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";
import type { Estimate, Job } from "../api/types";
import { usd } from "../lib/format";

const STATUS: Record<Job["status"], string> = {
  pending: "Bekliyor",
  running: "Çalışıyor",
  paused: "Duraklatıldı",
  done: "Bitti",
  failed: "Hatalı",
  cancelled: "İptal",
};

interface Props {
  api: EngineApi | null;
  bookId: number | null;
  refreshKey: number;
  requestConfirmed: <T>(est: () => Promise<Estimate>, run: (t: string) => Promise<T>, done?: (r: T) => void) => void;
  onChange: () => void;
}

export function JobsPanel({ api, bookId, refreshKey, requestConfirmed, onChange }: Props) {
  const [jobs, setJobs] = useState<Job[]>([]);

  const load = useCallback(async () => {
    if (!api) return;
    const list = await api.listJobs(bookId ?? undefined);
    const fresh = await Promise.all(list.map((j) => (j.status === "running" ? api.getJob(j.id) : j)));
    setJobs(fresh);
  }, [api, bookId]);

  useEffect(() => {
    void load();
  }, [load, refreshKey]);

  useEffect(() => {
    if (!jobs.some((j) => j.status === "running")) return;
    const t = window.setInterval(() => {
      void load();
      onChange();
    }, 1500);
    return () => window.clearInterval(t);
  }, [jobs, load, onChange]);

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
            {j.stop_reason && <p className="small warn">{j.stop_reason}</p>}
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
                <button type="button" onClick={() => void api.pauseJob(j.id).then(load)}>
                  Duraklat
                </button>
              )}
              {j.status === "paused" && (
                <button type="button" onClick={() => requestConfirmed(() => api.estimateResumeJob(j.id), (t) => api.resumeJob(j.id, t), () => void load())}>
                  Devam
                </button>
              )}
              {failed.length > 0 && j.status !== "running" && (
                <button type="button" onClick={() => requestConfirmed(() => api.estimateRetryFailed(j.id), (t) => api.retryFailed(j.id, t), () => void load())}>
                  Sadece hatalıları tekrar dene
                </button>
              )}
              {(j.status === "running" || j.status === "paused") && (
                <button type="button" onClick={() => void api.cancelJob(j.id).then(load)}>
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
