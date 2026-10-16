import { ArrowRight } from "@phosphor-icons/react";
import { Command } from "cmdk";
import { useState, type ReactNode } from "react";
import { Kbd } from "../ui";

export interface PaletteAction {
  id: string;
  label: string;
  group: string;
  icon?: ReactNode;
  shortcut?: string;
  keywords?: string[];
  disabled?: boolean;
  run: () => void;
}

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  actions: PaletteAction[];
  /** Typing a number offers "Sayfaya git: N". */
  pageCount: number;
  onGoto: (page: number) => void;
}

const GROUP_ORDER = ["Çeviri", "Görünüm", "Git", "Paneller", "Kitap", "Uygulama"];

/** Ctrl+K: every action, searchable. AI actions only open their cost confirmation. */
export function CommandPalette({ open, onOpenChange, actions, pageCount, onGoto }: Props) {
  const [search, setSearch] = useState("");
  const close = () => {
    onOpenChange(false);
    setSearch("");
  };
  const run = (fn: () => void) => {
    close();
    // After the dialog unmounts, so focus/modals opened by the action aren't fought over.
    window.setTimeout(fn, 0);
  };
  const n = Number(search.trim());
  const pageHit = pageCount > 0 && /^\d+$/.test(search.trim()) && n >= 1 && n <= pageCount ? n : null;
  const groups = GROUP_ORDER.map((g) => [g, actions.filter((a) => a.group === g)] as const).filter(([, list]) => list.length > 0);

  return (
    <Command.Dialog
      open={open}
      onOpenChange={(o) => (o ? onOpenChange(true) : close())}
      label="Komut paleti"
      className="palette__root"
      contentClassName="palette"
      overlayClassName="palette-scrim"
      loop
    >
      <Command.Input className="palette__input" value={search} onValueChange={setSearch} placeholder="Bir komut ya da sayfa numarası yazın…" />
      <Command.List className="palette__list">
        <Command.Empty className="palette__empty">Sonuç yok.</Command.Empty>
        {pageHit !== null && (
          <Command.Group heading="Git" className="palette__group">
            <Command.Item value={`sayfa ${pageHit} git`} className="palette__item" onSelect={() => run(() => onGoto(pageHit))}>
              <span className="palette__icon">
                <ArrowRight />
              </span>
              Sayfaya git: {pageHit}
            </Command.Item>
          </Command.Group>
        )}
        {groups.map(([group, list]) => (
          <Command.Group key={group} heading={group} className="palette__group">
            {list.map((a) => (
              <Command.Item
                key={a.id}
                value={`${a.label} ${(a.keywords ?? []).join(" ")}`}
                className="palette__item"
                disabled={a.disabled}
                onSelect={() => run(a.run)}
              >
                {a.icon && <span className="palette__icon">{a.icon}</span>}
                <span className="palette__label">{a.label}</span>
                {a.shortcut && (
                  <span className="palette__hint">
                    <Kbd>{a.shortcut}</Kbd>
                  </span>
                )}
              </Command.Item>
            ))}
          </Command.Group>
        ))}
      </Command.List>
    </Command.Dialog>
  );
}
