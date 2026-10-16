import { useEffect, useRef } from "react";
import type { Estimate } from "../api/types";
import { tokens, usd } from "../lib/format";

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
  useEffect(() => cancelRef.current?.focus(), []);
  const nothingToDo = e.calls === 0;

  return (
    <div className="modal-backdrop" role="presentation" onKeyDown={(ev) => ev.key === "Escape" && onCancel()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="cost-title">
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
