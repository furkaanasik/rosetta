import { Plug, Receipt } from "@phosphor-icons/react";
import * as Popover from "@radix-ui/react-popover";
import type { UsageTotals } from "../api/types";
import { tokens, usd } from "../lib/format";
import { Badge } from "../ui";

interface Props {
  connected: boolean;
  mock: boolean;
  usage: UsageTotals | null;
  /** Engine start-up failure or crash. */
  error?: string | null;
  /** Render inside the reader toolbar instead of floating over the page. */
  inline?: boolean;
}

/** Floating status "pill": engine state only when something is wrong, spend always (quietly). */
export function SpendPill({ connected, mock, usage, error = null, inline = false }: Props) {
  const problem = !connected || error !== null;
  return (
    <div className={inline ? "pill-dock pill-dock--inline" : "pill-dock"}>
      {problem && (
        <span className="pill pill--danger" role="alert" title={error ?? undefined}>
          <Plug aria-hidden="true" />
          {error ? `Motor hatası: ${error}` : "Motor bağlı değil"}
        </span>
      )}
      {mock && !problem && <Badge tone="amber">Deneme motoru</Badge>}
      <Popover.Root>
        <Popover.Trigger asChild>
          <button type="button" className="pill pill--spend num" data-testid="spend" aria-label="Harcama ayrıntısı">
            <Receipt aria-hidden="true" />
            <span>≈ {usd(usage?.cost_usd ?? 0)}</span>
            <span className="pill__extra">· {usage?.calls ?? 0} çağrı</span>
          </button>
        </Popover.Trigger>
        <Popover.Portal>
          <Popover.Content className="pop spend-pop" side={inline ? "bottom" : "top"} align="end" sideOffset={8}>
            <p className="pop__title">Toplam kullanım</p>
            <dl className="kv num">
              <dt>Çağrı</dt>
              <dd>{usage?.calls ?? 0}</dd>
              <dt>Girdi</dt>
              <dd>{tokens(usage?.input_tokens ?? 0)} token</dd>
              <dt>Çıktı</dt>
              <dd>{tokens(usage?.output_tokens ?? 0)} token</dd>
              <dt>Tutar</dt>
              <dd>≈ {usd(usage?.cost_usd ?? 0)}</dd>
            </dl>
            <p className="muted small">Liste fiyatı eşdeğeri — Max planında faturalanmaz. Her AI işlemi önce onay ister.</p>
          </Popover.Content>
        </Popover.Portal>
      </Popover.Root>
    </div>
  );
}
