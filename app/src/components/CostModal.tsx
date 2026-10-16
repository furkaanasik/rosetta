import { CircleNotch, Info, Sparkle, WarningCircle } from "@phosphor-icons/react";
import { useRef } from "react";
import type { Estimate } from "../api/types";
import { tokens, usd } from "../lib/format";
import { useModalFocus } from "../lib/useModalFocus";
import { Button } from "../ui";
import { compactTokens, compressPages } from "../ui/text";

/** What the user is about to pay for, in plain words. */
function title(e: Estimate): string {
  switch (e.operation) {
    case "translate":
      return e.pages.length === 1 ? "Bu sayfayı çevir" : `${e.pages.length} sayfayı çevir`;
    case "job":
      return "Toplu çeviri";
    case "profile":
      return "Kitabı analiz et";
    case "explain":
      return "Bunu açıkla";
  }
}

function scope(e: Estimate): string {
  const parts: string[] = [];
  if (e.pages.length === 1) parts.push(`Sayfa ${e.pages[0]}`);
  else if (e.pages.length > 1) parts.push(`Sayfa ${compressPages(e.pages)}`);
  if (e.total_blocks > 0) {
    parts.push(e.cached_blocks > 0 ? `${e.total_blocks} paragraf · ${e.cached_blocks} önbellekte` : `${e.total_blocks} paragraf`);
  }
  parts.push(e.model);
  return parts.join(" · ");
}

interface Props {
  estimate: Estimate;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/**
 * Cost confirmation (rule 2): nothing runs until the user presses "Onayla". Default focus is on
 * İptal (Enter cancels), Tab stays inside, Escape cancels — except while the confirmed call
 * runs, because it can't be undone and hiding the dialog would look like a cancellation.
 */
export function CostModal({ estimate: e, busy = false, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalFocus(dialogRef, () => !busy && onCancel(), cancelRef);
  const nothingToDo = e.calls === 0;
  const name = title(e);

  return (
    <div className="dialog-scrim" role="presentation">
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="dialog cost"
        role="dialog"
        aria-modal="true"
        aria-label={`${name} — maliyet onayı`}
        aria-busy={busy}
      >
        <header className="cost__head">
          <h2 className="cost__title">{name}</h2>
          <p className="cost__scope">{scope(e)}</p>
        </header>

        <div className="cost__figure">
          <p className={`cost__usd${e.price_known ? "" : " cost__usd--unknown"}`} data-testid="cost-usd">
            {e.price_known ? `≈ ${usd(e.usd)}` : "fiyat bilinmiyor"}
          </p>
          <dl className="cost__metrics">
            <div>
              <dt className="visually-hidden">Çağrı</dt>
              <dd>
                <span data-testid="cost-calls">{e.calls}</span> çağrı
              </dd>
            </div>
            <div>
              <dt className="visually-hidden">Tahmini token</dt>
              <dd title={`girdi ≈ ${tokens(e.input_tokens)} · çıktı ≈ ${tokens(e.output_tokens)}`}>
                ~{compactTokens(e.input_tokens + e.output_tokens)} token
              </dd>
            </div>
          </dl>
          <p className="cost__basis">
            {e.price_known ? "liste fiyatı eşdeğeri — Max planında faturalanmaz" : "bu model için fiyat tanımlı değil (config.toml → [pricing])"}
          </p>
        </div>

        {(e.warnings ?? []).map((w) => (
          <p key={w} className="cost__note cost__note--warn" role="alert">
            <WarningCircle aria-hidden="true" />
            <span>{w}</span>
          </p>
        ))}
        {!e.supports_profile && (
          <p className="cost__note cost__note--warn">
            <WarningCircle aria-hidden="true" />
            <span>Bu sağlayıcı kitap profilini ve bağlamı kullanmaz.</span>
          </p>
        )}
        {nothingToDo && (
          <p className="cost__note">
            <Info aria-hidden="true" />
            <span>Tümü önbellekte — AI çağrısı yapılmayacak.</span>
          </p>
        )}
        {e.thinking && (
          <details className="cost__details">
            <summary>
              <Sparkle aria-hidden="true" />
              <span>Düşünme: {e.thinking}</span>
            </summary>
            <p>
              Çağrı başına ≈ +{tokens(e.thinking_extra_tokens)} token eklenir; gerçek değer ±%40 değişebilir. Girdi ≈{" "}
              {tokens(e.input_tokens)}, çıktı ≈ {tokens(e.output_tokens)} token · {e.provider} / {e.model}.
            </p>
          </details>
        )}

        <div className="dialog__actions">
          <Button ref={cancelRef} variant="secondary" onClick={onCancel} disabled={busy}>
            İptal
          </Button>
          <Button
            variant="primary"
            onClick={onConfirm}
            disabled={busy}
            icon={busy ? <CircleNotch className="spin" /> : undefined}
          >
            {busy ? "Çalışıyor…" : "Onayla"}
          </Button>
        </div>
      </div>
    </div>
  );
}
