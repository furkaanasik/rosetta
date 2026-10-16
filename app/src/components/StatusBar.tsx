import type { UsageTotals } from "../api/types";
import { tokens, usd } from "../lib/format";

interface Props {
  connected: boolean;
  mock: boolean;
  usage: UsageTotals | null;
  message: string | null;
  /** Engine start-up failure or crash. */
  error?: string | null;
}

export function StatusBar({ connected, mock, usage, message, error = null }: Props) {
  return (
    <footer className="statusbar">
      <span className={connected ? "dot ok" : "dot off"} aria-hidden="true" />
      <span>{connected ? (mock ? "Motor: deneme (mock)" : "Motor bağlı") : "Motor bağlı değil"}</span>
      {error && (
        <span className="status-error" role="alert" title={error}>
          {error}
        </span>
      )}
      {message && <span className="status-msg" role="status">{message}</span>}
      <span className="spacer" />
      <span data-testid="spend" title="Toplam harcama (liste fiyatı eşdeğeri)">
        Harcama: {usage ? `${usage.calls} çağrı · ${tokens(usage.input_tokens + usage.output_tokens)} tok · ${usd(usage.cost_usd)}` : "–"}
      </span>
    </footer>
  );
}
