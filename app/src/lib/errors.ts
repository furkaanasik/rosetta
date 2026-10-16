import { EngineError } from "../api/types";

/** Where an error toast's action button leads. */
export type ErrorAction = "settings" | "jobs";

export interface ErrorView {
  message: string;
  action?: ErrorAction;
}

const FIXED: Partial<Record<EngineError["kind"], string>> = {
  usage_limit: "Kullanım limitine ulaşıldı — iş duraklatıldı.",
  auth: "Claude girişi yok: terminalde `claude` ile giriş yapın.",
  budget: "Bütçe sınırı aşıldı — durdu.",
  expired_token: "Onayın süresi doldu; tahmini yeniden alın.",
  conflict: "Kitap dosyası kayıtlı yolda değişmiş; PDF'i yeniden açın.",
  offline: "Motor bağlantısı yok — Rosetta'yı yeniden başlatmayı deneyin.",
};

/**
 * User-facing text for an engine error. Engine down, provider missing and "another AI job is
 * busy" used to share one generic sentence; each now says what happened and what to do.
 */
export function describeError(e: unknown): ErrorView {
  if (!(e instanceof EngineError)) {
    return { message: e instanceof Error ? e.message : String(e) };
  }
  switch (e.kind) {
    case "busy":
      return { message: e.message || "Başka bir AI işlemi sürüyor; bitince tekrar deneyin.", action: "jobs" };
    case "unavailable": {
      const provider = /claude cli|claude bulunamad|ollama|deepl|sağlayıcı/i.test(e.message);
      return {
        message: e.message || "Çeviri sağlayıcısı kullanılamıyor.",
        action: provider ? "settings" : undefined,
      };
    }
    case "auth":
      return { message: FIXED.auth!, action: "settings" };
    default:
      return { message: FIXED[e.kind] ?? e.message };
  }
}

export const ERROR_ACTION_LABEL: Record<ErrorAction, string> = {
  settings: "Ayarlar",
  jobs: "İşleri aç",
};
