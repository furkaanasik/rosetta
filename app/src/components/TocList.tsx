import { ListBullets } from "@phosphor-icons/react";
import { useEffect, useRef, type CSSProperties } from "react";
import type { OutlineItem } from "../lib/pdf";
import { cx, EmptyState } from "../ui";

interface Props {
  items: OutlineItem[];
  current: number;
  onGo: (page: number) => void;
}

/** Index of the section the reader is in: the last entry starting at or before the current page. */
export function currentSection(items: OutlineItem[], page: number): number {
  let found = -1;
  items.forEach((it, i) => {
    if (it.page !== null && it.page <= page && (found < 0 || it.page >= (items[found]!.page ?? 0))) found = i;
  });
  return found;
}

/** Table of contents: tree indentation, right-aligned tabular page numbers, current section marked. */
export function TocList({ items, current, onGo }: Props) {
  const active = currentSection(items, current);
  const activeRef = useRef<HTMLButtonElement>(null);
  // Keep the current section visible by scrolling only the panel's own list — never
  // scrollIntoView, which would also scroll the (overflow-hidden) reader to an off-screen panel.
  useEffect(() => {
    const item = activeRef.current;
    const box = item?.closest<HTMLElement>(".side-panel__body");
    if (!item || !box) return;
    const top = item.offsetTop - box.offsetTop;
    if (top < box.scrollTop) box.scrollTop = top - 8;
    else if (top + item.offsetHeight > box.scrollTop + box.clientHeight) box.scrollTop = top + item.offsetHeight - box.clientHeight + 8;
  }, [active]);

  if (items.length === 0)
    return <EmptyState size="compact" icon={<ListBullets />} title="İçindekiler yok">Bu PDF bir içindekiler tablosu içermiyor.</EmptyState>;

  return (
    <nav className="toc" aria-label="İçindekiler">
      <ul>
        {items.map((it, i) => (
          <li key={i} style={{ "--toc-level": Math.max(0, it.level - 1) } as CSSProperties}>
            <button
              ref={i === active ? activeRef : undefined}
              type="button"
              className={cx("toc__item", it.level <= 1 && "toc__item--top", i === active && "is-current")}
              aria-current={i === active ? "location" : undefined}
              disabled={it.page === null}
              onClick={() => it.page !== null && onGo(it.page)}
            >
              <span className="toc__title">{it.title}</span>
              {it.page !== null && <span className="toc__page num">{it.page}</span>}
            </button>
          </li>
        ))}
      </ul>
    </nav>
  );
}
