import { useEffect, useState } from "react";
import type { EngineApi } from "../api/engine";

/** Cover thumbnail fetched with the bearer token (blob URL); a typographic cover until/unless it loads. */
export function Cover({ api, bookId, title }: { api: EngineApi | null; bookId: number; title: string }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!api) return;
    let cancelled = false;
    let made: string | null = null;
    api
      .coverBlob(bookId, 240)
      .then((b) => {
        if (cancelled || b.size < 100) return; // tiny/blank placeholder → keep the typographic cover
        made = URL.createObjectURL(b);
        setUrl(made);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      if (made) URL.revokeObjectURL(made);
    };
  }, [api, bookId]);

  return (
    <div className="cover">
      {url ? (
        <img src={url} alt="" className="cover__img" />
      ) : (
        <div className="cover__type" aria-hidden="true">
          <span className="cover__rule" />
          <span className="cover__title">{title}</span>
        </div>
      )}
    </div>
  );
}
