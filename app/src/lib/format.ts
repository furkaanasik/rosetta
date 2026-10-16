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
