import { useState } from "react";
import type { ExportMode } from "../api/types";

interface Props {
  connected: boolean;
  hasBook: boolean;
  page: number;
  busy: boolean;
  onAnalyze: () => void;
  onTranslatePage: () => void;
  onTranslateRange: (spec: string, budget: number | null) => void;
  onTranslateAll: (budget: number | null) => void;
  onExport: (mode: ExportMode) => void;
}

/** Manual buttons only (rule 1): every AI action goes through the cost modal. */
export function ControlPanel(p: Props) {
  const [range, setRange] = useState("");
  const [budget, setBudget] = useState("");
  const [exportMode, setExportMode] = useState<ExportMode>("tr");
  const disabled = !p.connected || !p.hasBook || p.busy;
  const why = !p.connected ? "Motor bağlı değil" : !p.hasBook ? "Önce bir PDF açın" : undefined;
  const budgetValue = budget.trim() ? Number(budget.replace(",", ".")) : null;

  return (
    <section className="panel" aria-label="Kontrol paneli">
      <h3>Çeviri</h3>
      <button type="button" disabled={disabled} title={why} onClick={p.onAnalyze}>
        Kitabı Analiz Et
      </button>
      <button type="button" className="primary" disabled={disabled} title={why} onClick={p.onTranslatePage}>
        Bu Sayfayı Çevir ({p.page})
      </button>
      <label className="field">
        <span>Aralık</span>
        <input placeholder="ör. 120-140" value={range} onChange={(e) => setRange(e.target.value)} />
      </label>
      <label className="field">
        <span>Bütçe ($, opsiyonel)</span>
        <input inputMode="decimal" placeholder="ör. 2" value={budget} onChange={(e) => setBudget(e.target.value)} />
      </label>
      <button
        type="button"
        disabled={disabled || !range.trim()}
        title={why}
        onClick={() => p.onTranslateRange(range, budgetValue)}
      >
        Aralık Çevir
      </button>
      <button type="button" disabled={disabled} title={why} onClick={() => p.onTranslateAll(budgetValue)}>
        Tüm Kitabı Çevir
      </button>
      <h3>Dışa aktar</h3>
      <div className="row">
        <select aria-label="Dışa aktarma modu" value={exportMode} onChange={(e) => setExportMode(e.target.value as ExportMode)}>
          <option value="tr">Sadece Türkçe</option>
          <option value="bilingual">İki dilli (EN | TR)</option>
        </select>
        <button type="button" disabled={disabled} title={why} onClick={() => p.onExport(exportMode)}>
          PDF Dışa Aktar
        </button>
      </div>
      <p className="muted small">AI işlemleri yalnızca butonla ve onayınızla çalışır.</p>
    </section>
  );
}
