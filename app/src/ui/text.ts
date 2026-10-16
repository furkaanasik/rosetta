// Human-facing formatting for the shell (Turkish).

/** [120,121,122,130] → "120–122, 130". */
export function compressPages(pages: number[]): string {
  const sorted = [...new Set(pages)].sort((a, b) => a - b);
  const out: string[] = [];
  for (let i = 0; i < sorted.length; ) {
    let j = i;
    while (j + 1 < sorted.length && sorted[j + 1] === sorted[j]! + 1) j++;
    out.push(i === j ? `${sorted[i]}` : `${sorted[i]}–${sorted[j]}`);
    i = j + 1;
  }
  return out.join(", ");
}

/** 5634 → "5,6 bin"; 812 → "812". */
export function compactTokens(n: number): string {
  if (n < 1000) return String(Math.round(n));
  const k = n / 1000;
  return `${k.toLocaleString("tr-TR", { maximumFractionDigits: k < 10 ? 1 : 0 })} bin`;
}

/** "az önce", "5 dk önce", "3 saat önce", "dün", "4 gün önce", or a date. */
export function relativeTime(iso: string | null | undefined, now: number = Date.now()): string {
  if (!iso) return "";
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, (now - t) / 1000);
  if (s < 60) return "az önce";
  if (s < 3600) return `${Math.floor(s / 60)} dk önce`;
  if (s < 86400) return `${Math.floor(s / 3600)} saat önce`;
  const d = Math.floor(s / 86400);
  if (d === 1) return "dün";
  if (d < 7) return `${d} gün önce`;
  return new Date(t).toLocaleDateString("tr-TR", { day: "numeric", month: "short", year: "numeric" });
}

/** "%9" — share as a whole percent, at least 1% when anything is done. */
export function percent(part: number, total: number): string {
  if (total <= 0 || part <= 0) return "%0";
  return `%${Math.max(1, Math.round((part / total) * 100))}`;
}
