import { useRef } from "react";
import type { Estimate } from "../api/types";
import { tokens, usd } from "../lib/format";
import { useModalFocus } from "../lib/useModalFocus";

const OPERATION_LABELS: Record<Estimate["operation"], string> = {
  translate: "Çeviri",
  job: "Toplu çeviri işi",
  profile: "Kitap analizi (profil)",
  explain: "Bunu açıkla",
};

interface Props {
  estimate: Estimate;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Cost confirmation (rule 2): nothing runs until the user presses "Onayla". */
export function CostModal({ estimate: e, busy = false, onConfirm, onCancel }: Props) {
  const cancelRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  // While the confirmed call runs it can't be undone: Escape must not hide it (the request
  // would keep running and spending while the user thinks it was cancelled).
  useModalFocus(dialogRef, () => !busy && onCancel(), cancelRef);
  const nothingToDo = e.calls === 0;

  return (
    <div className="modal-backdrop" role="presentation">
      <div ref={dialogRef} tabIndex={-1} className="modal" role="dialog" aria-modal="true" aria-labelledby="cost-title" aria-busy={busy}>
        <h2 id="cost-title">{OPERATION_LABELS[e.operation]} — maliyet onayı</h2>
        <dl className="cost-grid">
          <dt>Sağlayıcı / model</dt>
          <dd>
            {e.provider} / {e.model}
          </dd>
          {e.pages.length > 0 && (
            <>
              <dt>Sayfa</dt>
              <dd>{e.pages.length}</dd>
            </>
          )}
          {e.total_blocks > 0 && (
            <>
              <dt>Cache</dt>
              <dd>
                {e.cached_blocks}/{e.total_blocks} block hazır
              </dd>
            </>
          )}
          <dt>Çağrı</dt>
          <dd data-testid="cost-calls">{e.calls}</dd>
          <dt>Tahmini token</dt>
          <dd>
            girdi ≈ {tokens(e.input_tokens)} · çıktı ≈ {tokens(e.output_tokens)}
          </dd>
          <dt>Tahmini tutar</dt>
          <dd data-testid="cost-usd">
            {e.price_known ? `≈ ${usd(e.usd)}` : "fiyat bilinmiyor"}{" "}
            <span className="muted">(liste fiyatı eşdeğeri)</span>
          </dd>
        </dl>
        {e.thinking && (
          <p className="note">
            Düşünme: {e.thinking} — çağrı başı ≈ +{tokens(e.thinking_extra_tokens)} token; gerçek
            değer ±%40 değişebilir.
          </p>
        )}
        {!e.supports_profile && (
          <p className="note warn">Bu sağlayıcı kitap profilini ve bağlamı kullanmaz.</p>
        )}
        {nothingToDo && <p className="note">Tümü cache'te — AI çağrısı yapılmayacak.</p>}
        {(e.warnings ?? []).map((w) => (
          <p key={w} className="note warn" role="alert">
            {w}
          </p>
        ))}
        <div className="modal-actions">
          <button ref={cancelRef} type="button" onClick={onCancel} disabled={busy}>
            İptal
          </button>
          <button type="button" className="primary" onClick={onConfirm} disabled={busy}>
            {busy ? "Çalışıyor…" : "Onayla"}
          </button>
        </div>
      </div>
    </div>
  );
}
