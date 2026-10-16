const nf = new Intl.NumberFormat("tr-TR");

export function tokens(n: number): string {
  return nf.format(Math.round(n));
}

export function usd(n: number): string {
  return `$${n.toFixed(n < 0.1 ? 3 : 2)}`;
}

/** "1-3,5" → [1,2,3,5] (1-based, sorted, unique). Throws on bad input. */
export function parsePageSpec(spec: string, pageCount: number): number[] {
  const out = new Set<number>();
  for (const part of spec.replace(/\s+/g, "").split(",")) {
    if (!part) continue;
    const m = /^(\d+)(?:-(\d+))?$/.exec(part);
    if (!m) throw new Error(`Geçersiz sayfa: ${part}`);
    const a = Number(m[1]);
    const b = m[2] ? Number(m[2]) : a;
    if (a < 1 || b < a || b > pageCount) throw new Error(`Aralık dışı: ${part}`);
    for (let p = a; p <= b; p++) out.add(p);
  }
  if (!out.size) throw new Error("Sayfa girilmedi");
  return [...out].sort((x, y) => x - y);
}

/** Turkish text for the engine's (English) job/translation stop reasons; unknown ones pass through. */
export function stopReasonText(reason: string): string {
  if (reason === "pause requested") return "Duraklatma istendi.";
  const budget = /^budget \$([\d.]+) would be exceeded \(spent \$([\d.]+) \+ next batch ≈ \$([\d.]+)\)$/.exec(reason);
  if (budget) return `Bütçe sınırı ($${budget[1]}) aşılacaktı: harcanan $${budget[2]} + sonraki batch ≈ $${budget[3]}.`;
  const errors = /^(\d+) consecutive provider errors; last: (.*)$/s.exec(reason);
  if (errors) return `Üst üste ${errors[1]} sağlayıcı hatası; sonuncusu: ${errors[2]}`;
  return reason;
}
