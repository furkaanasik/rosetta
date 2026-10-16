import { ArrowClockwise, Books, CaretDown, Export, FilePdf, MagicWand, Rows, Translate } from "@phosphor-icons/react";
import * as Menu from "@radix-ui/react-dropdown-menu";
import * as Popover from "@radix-ui/react-popover";
import { useRef, useState, type FormEvent } from "react";
import type { ExportMode } from "../api/types";
import { Button, Kbd } from "../ui";

export interface TranslateActions {
  /** Why AI actions are unavailable (no engine, no book) — shown as the tooltip; null = enabled. */
  disabledReason: string | null;
  busy: boolean;
  page: number;
  pageCount: number;
  onTranslatePage: () => void;
  onRetranslatePage: () => void;
  onTranslateRange: (spec: string, budget: number | null) => void;
  onTranslateAll: (budget: number | null) => void;
  onAnalyze: () => void;
  onExport: (mode: ExportMode) => void;
}

export type RangeKind = "range" | "all";

/**
 * The single primary action: "Çevir" translates this page; the caret opens range / whole book /
 * analyze / export. Every AI item goes through the estimate → cost-confirmation gate (rules 1–2).
 */
export function TranslateMenu(
  p: TranslateActions & { rangeOpen: RangeKind | null; onRangeOpen: (k: RangeKind | null) => void; rangeSeed?: string },
) {
  const disabled = p.disabledReason !== null || p.busy;
  const opening = useRef(false);

  const openRange = (kind: RangeKind) => {
    opening.current = true;
    // Let the menu close first, then anchor the popover to the same button.
    window.setTimeout(() => p.onRangeOpen(kind), 0);
  };

  return (
    <Popover.Root open={p.rangeOpen !== null} onOpenChange={(o) => !o && p.onRangeOpen(null)}>
      <Popover.Anchor asChild>
        <div className="split-btn" title={p.disabledReason ?? undefined}>
          <Button
            variant="primary"
            className="split-btn__main"
            icon={<Translate />}
            disabled={disabled}
            onClick={p.onTranslatePage}
            aria-label={`Bu sayfayı çevir (sayfa ${p.page})`}
          >
            Çevir
          </Button>
          <Menu.Root modal={false}>
            <Menu.Trigger asChild>
              <Button variant="primary" className="split-btn__more" disabled={p.disabledReason !== null} aria-label="Diğer çeviri seçenekleri">
                <CaretDown aria-hidden="true" />
              </Button>
            </Menu.Trigger>
            <Menu.Portal>
              <Menu.Content
                className="menu"
                align="end"
                sideOffset={8}
                onCloseAutoFocus={(e) => {
                  if (opening.current) {
                    e.preventDefault();
                    opening.current = false;
                  }
                }}
              >
                <Menu.Label className="menu__label">Çeviri</Menu.Label>
                <Menu.Item className="menu__item" disabled={disabled} onSelect={p.onTranslatePage}>
                  <span className="menu__icon">
                    <Translate />
                  </span>
                  Bu sayfayı çevir
                  <span className="menu__hint">
                    <Kbd>T</Kbd>
                  </span>
                </Menu.Item>
                <Menu.Item className="menu__item" disabled={disabled} onSelect={p.onRetranslatePage}>
                  <span className="menu__icon">
                    <ArrowClockwise />
                  </span>
                  Bu sayfayı yeniden çevir…
                </Menu.Item>
                <Menu.Item className="menu__item" disabled={disabled} onSelect={() => openRange("range")}>
                  <span className="menu__icon">
                    <Rows />
                  </span>
                  Aralık çevir…
                </Menu.Item>
                <Menu.Item className="menu__item" disabled={disabled} onSelect={() => openRange("all")}>
                  <span className="menu__icon">
                    <Books />
                  </span>
                  Tüm kitabı çevir…
                </Menu.Item>
                <Menu.Separator className="menu__sep" />
                <Menu.Label className="menu__label">Kitap</Menu.Label>
                <Menu.Item className="menu__item" disabled={disabled} onSelect={p.onAnalyze}>
                  <span className="menu__icon">
                    <MagicWand />
                  </span>
                  Kitabı analiz et…
                </Menu.Item>
                <Menu.Item className="menu__item" disabled={p.disabledReason !== null} onSelect={() => p.onExport("tr")}>
                  <span className="menu__icon">
                    <FilePdf />
                  </span>
                  PDF olarak dışa aktar — Türkçe
                </Menu.Item>
                <Menu.Item className="menu__item" disabled={p.disabledReason !== null} onSelect={() => p.onExport("bilingual")}>
                  <span className="menu__icon">
                    <Export />
                  </span>
                  PDF olarak dışa aktar — iki dilli
                </Menu.Item>
              </Menu.Content>
            </Menu.Portal>
          </Menu.Root>
        </div>
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content className="pop range-pop" align="end" sideOffset={8} aria-label={p.rangeOpen === "all" ? "Tüm kitabı çevir" : "Aralık çevir"}>
          {p.rangeOpen && <RangeForm {...p} kind={p.rangeOpen} seed={p.rangeSeed ?? ""} onDone={() => p.onRangeOpen(null)} />}
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

function RangeForm(p: TranslateActions & { kind: RangeKind; seed: string; onDone: () => void }) {
  const [range, setRange] = useState(p.seed);
  const [budget, setBudget] = useState("");
  const budgetValue = budget.trim() ? Number(budget.replace(",", ".")) : null;
  const badBudget = budgetValue !== null && !(budgetValue > 0);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (badBudget) return;
    if (p.kind === "range") {
      if (!range.trim()) return;
      p.onTranslateRange(range, budgetValue);
    } else {
      p.onTranslateAll(budgetValue);
    }
    p.onDone();
  };
  return (
    <form className="range-form" onSubmit={submit}>
      <p className="pop__title">{p.kind === "range" ? "Aralık çevir" : "Tüm kitabı çevir"}</p>
      <p className="muted small">
        {p.kind === "range"
          ? "Toplu iş olarak çalışır: duraklatılabilir, bütçeyle sınırlanabilir."
          : `${p.pageCount} sayfa toplu iş olarak çevrilir; önbellektekiler tekrar ödenmez.`}
      </p>
      {p.kind === "range" && (
        <label className="field">
          <span>Sayfalar</span>
          <input autoFocus placeholder="ör. 120-140" value={range} onChange={(e) => setRange(e.target.value)} />
        </label>
      )}
      <label className="field">
        <span>Bütçe ($, isteğe bağlı)</span>
        <input
          autoFocus={p.kind === "all"}
          inputMode="decimal"
          placeholder="ör. 2"
          value={budget}
          aria-invalid={badBudget}
          onChange={(e) => setBudget(e.target.value)}
        />
      </label>
      <div className="range-form__actions">
        <Button variant="ghost" size="sm" onClick={p.onDone}>
          Vazgeç
        </Button>
        <Button type="submit" variant="primary" size="sm" disabled={(p.kind === "range" && !range.trim()) || badBudget}>
          {p.kind === "range" ? "Aralığı çevir" : "Tümünü çevir"}
        </Button>
      </div>
      <p className="muted small">Başlatmadan önce maliyet tahmini gösterilir.</p>
    </form>
  );
}
