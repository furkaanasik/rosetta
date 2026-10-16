import DOMPurify from "dompurify";

/**
 * Defence in depth for engine-produced HTML. The engine already escapes all book and model
 * text; here an allowlist (DOMPurify) keeps only the markup the engine emits.
 *
 * Images are never given a URL here: `<img src="assets/x.png">` becomes
 * `<img data-asset="x.png">` and the pane loads it with the bearer token (blob URL), so the
 * token never appears in the DOM.
 */
const ALLOWED_TAGS = [
  "main", "section", "article", "header", "footer", "nav", "div", "span", "p", "br", "hr",
  "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "aside",
  "ul", "ol", "li", "pre", "code", "kbd", "samp",
  "em", "strong", "b", "i", "u", "s", "sub", "sup", "small", "mark",
  "figure", "figcaption", "img",
  "table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption", "colgroup", "col",
  "ruby", "rt", "rp",
];

const ALLOWED_ATTR = [
  "class", "title", "lang", "id", "value", "start", "src", "alt", "role", "aria-hidden",
  "aria-label", "colspan", "rowspan", "style",
];

/** The only inline style the engine writes: the original point size (rule 4, no shrinking). */
const FONT_SIZE_STYLE = /^\s*font-size:\s*calc\(var\(--scale\)\s*\*\s*\d+(\.\d+)?pt\)\s*;?\s*$/;
const ASSET_NAME = /^[A-Za-z0-9._-]+\.(png|jpe?g|webp)$/i;

let hooksInstalled = false;
const pendingAssets = new WeakMap<Node, string>();

function installHooks(purify: typeof DOMPurify): void {
  if (hooksInstalled) return;
  hooksInstalled = true;
  purify.addHook("uponSanitizeAttribute", (node, data) => {
    const name = data.attrName;
    if (name === "style") {
      data.keepAttr = FONT_SIZE_STYLE.test(data.attrValue);
    } else if (name === "src") {
      // Only engine assets survive, and only as data-asset (see module doc).
      const value = data.attrValue.trim();
      data.keepAttr = false;
      if (node.nodeName === "IMG" && value.startsWith("assets/")) {
        const asset = value.slice("assets/".length);
        if (ASSET_NAME.test(asset)) pendingAssets.set(node, asset);
      }
    } else if (name === "data-asset") {
      // Never trust a data-asset attribute coming from the input itself.
      data.keepAttr = false;
    }
  });
  purify.addHook("afterSanitizeAttributes", (node) => {
    const asset = pendingAssets.get(node);
    if (asset !== undefined) {
      (node as Element).setAttribute("data-asset", asset);
      pendingAssets.delete(node);
    }
  });
}

/** Valid engine asset name (as produced by the sanitizer's data-asset). */
export function isAssetName(name: string): boolean {
  return ASSET_NAME.test(name);
}

export function sanitizeEngineHtml(html: string): string {
  installHooks(DOMPurify);
  const fragment = DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: true,
    ALLOW_ARIA_ATTR: false,
    RETURN_DOM_FRAGMENT: true,
    KEEP_CONTENT: true,
  });

  // Code callouts ❶–❿ (U+2776–U+277F) need a symbol font that may not be installed: draw them
  // as CSS circles with the plain digit instead.
  for (const el of Array.from(fragment.querySelectorAll<HTMLElement>(".callout"))) {
    const code = (el.textContent ?? "").trim().codePointAt(0) ?? 0;
    if (code >= 0x2776 && code <= 0x277f) {
      const n = String(code - 0x2775);
      el.textContent = n;
      el.classList.add("callout-num");
      el.setAttribute("aria-label", n);
    }
  }
  const holder = document.createElement("div");
  holder.appendChild(fragment);
  return holder.innerHTML;
}
