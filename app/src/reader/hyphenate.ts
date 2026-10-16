// Turkish hyphenation by syllables (soft hyphens), because browsers/WebKitGTK often ship no
// Turkish hyphenation dictionary and `hyphens: auto` then does nothing — justified text gets
// rivers. Turkish syllabification is regular: a new syllable starts at the consonant right before
// a vowel (ka-pı, ar-ka, kork-mak, sant-ral), so hyphenation needs no dictionary.

const VOWELS = "aeıioöuüâîûAEIİOÖUÜÂÎÛ";
const LETTER = /[a-zçğıöşüâîûA-ZÇĞİÖŞÜÂÎÛ]/;
const SHY = "­";

function isVowel(ch: string): boolean {
  return VOWELS.includes(ch);
}

/** Syllable start offsets (excluding 0) of one Turkish word. */
export function syllableBreaks(word: string): number[] {
  const out: number[] = [];
  for (let i = 1; i < word.length; i++) {
    // A consonant followed by a vowel starts a syllable, if a vowel came before it.
    const c = word[i]!;
    const next = word[i + 1];
    if (!isVowel(c) && next !== undefined && isVowel(next) && LETTER.test(c)) {
      let hasVowelBefore = false;
      for (let j = 0; j < i; j++) if (isVowel(word[j]!)) hasVowelBefore = true;
      if (hasVowelBefore) out.push(i);
    } else if (isVowel(c) && isVowel(word[i - 1]!)) {
      // Two vowels in a row belong to different syllables (sa-at, şi-ir).
      out.push(i);
    }
  }
  return out;
}

/**
 * Inserts soft hyphens into words of at least `minWord` letters, keeping ≥2 letters before and
 * ≥3 after a break. Only pure letter runs are touched (no code, numbers, URLs, acronyms).
 */
export function hyphenateTurkish(text: string, minWord = 7): string {
  return text.replace(/[a-zçğıöşüâîûA-ZÇĞİÖŞÜÂÎÛ]+/g, (word) => {
    if (word.length < minWord || word === word.toUpperCase()) return word;
    const breaks = syllableBreaks(word).filter((b) => b >= 2 && word.length - b >= 3);
    if (!breaks.length) return word;
    let out = "";
    let last = 0;
    for (const b of breaks) {
      out += word.slice(last, b) + SHY;
      last = b;
    }
    return out + word.slice(last);
  });
}

/** Soft-hyphenates the prose text of a Turkish page (not code, headings or inline code). */
export function hyphenateTree(root: HTMLElement): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) =>
      n.parentElement?.closest("code, pre, h1, h2, h3, h4, h5, h6, .h-label, rt, .untranslated, .rs-epigraph")
        ? NodeFilter.FILTER_REJECT
        : NodeFilter.FILTER_ACCEPT,
  });
  for (let n = walker.nextNode() as Text | null; n; n = walker.nextNode() as Text | null) {
    const next = hyphenateTurkish(n.data);
    if (next !== n.data) n.data = next;
  }
}

/** Removes soft hyphens (selection / copied sentence text). */
export function stripSoftHyphens(text: string): string {
  return text.replace(/­/g, "");
}
