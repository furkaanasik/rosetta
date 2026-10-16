import type { OutlineItem } from "../lib/pdf";

interface Props {
  items: OutlineItem[];
  current: number;
  onGo: (page: number) => void;
}

export function Sidebar({ items, current, onGo }: Props) {
  return (
    <aside className="sidebar" aria-label="İçindekiler">
      <h3>İçindekiler</h3>
      {items.length === 0 && <p className="muted">İçindekiler yok.</p>}
      <ul>
        {items.map((it, i) => (
          <li key={i} style={{ paddingLeft: (it.level - 1) * 12 }}>
            <button
              type="button"
              className={it.page === current ? "link active" : "link"}
              disabled={it.page === null}
              onClick={() => it.page !== null && onGo(it.page)}
            >
              {it.title}
              {it.page !== null && <span className="muted"> {it.page}</span>}
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
