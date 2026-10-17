import { X } from "@phosphor-icons/react";
import * as Tabs from "@radix-ui/react-tabs";
import type { ReactNode } from "react";
import { PANEL_LABELS, type SidePanel as Tab } from "../state";
import { IconButton } from "../ui";

interface Props {
  open: boolean;
  tab: Tab;
  onTab: (tab: Tab) => void;
  onClose: () => void;
  toc: ReactNode;
  jobs: ReactNode;
  words: ReactNode;
  profile: ReactNode;
  consistency: ReactNode;
}

const TABS: Tab[] = ["toc", "jobs", "words", "profile", "consistency"];

/**
 * Slide-over panel from the right (closed by default). It stays mounted while closed — inert
 * and off-screen — so the jobs tab keeps polling running jobs and the pages refresh.
 */
export function SidePanel({ open, tab, onTab, onClose, toc, jobs, words, profile, consistency }: Props) {
  const content: Record<Tab, ReactNode> = { toc, jobs, words, profile, consistency };
  return (
    <aside className="side-panel" data-open={open} aria-label="Yan panel" aria-hidden={!open} inert={!open}>
      <Tabs.Root value={tab} onValueChange={(v) => onTab(v as Tab)} className="side-panel__inner">
        <header className="side-panel__head">
          <Tabs.List aria-label="Paneller" className="side-tabs">
            {TABS.map((t) => (
              <Tabs.Trigger key={t} value={t} className="side-tabs__tab">
                {PANEL_LABELS[t]}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <IconButton label="Paneli kapat" size="sm" onClick={onClose}>
            <X />
          </IconButton>
        </header>
        {TABS.map((t) =>
          // Jobs stay mounted (polling); the others mount when their tab is shown.
          t === "jobs" ? (
            <Tabs.Content key={t} value={t} forceMount hidden={tab !== t} className="side-panel__body">
              {content[t]}
            </Tabs.Content>
          ) : (
            <Tabs.Content key={t} value={t} className="side-panel__body">
              {content[t]}
            </Tabs.Content>
          ),
        )}
      </Tabs.Root>
    </aside>
  );
}
