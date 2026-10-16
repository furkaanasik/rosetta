/**
 * Defence in depth for engine-produced HTML. The engine already escapes all book and model
 * text; here we still drop anything executable and rewrite asset URLs.
 */
const DROP_TAGS = new Set([
  "script",
  "iframe",
  "object",
  "embed",
  "link",
  "meta",
  "base",
  "form",
  "input",
  "button",
  "textarea",
  "select",
  "style",
]);

export function sanitizeEngineHtml(html: string, assetUrl: (name: string) => string): string {
  const doc = new DOMParser().parseFromString(`<div id="root">${html}</div>`, "text/html");
  const root = doc.getElementById("root");
  if (!root) return "";
  const all = Array.from(root.querySelectorAll("*"));
  for (const el of all) {
    if (DROP_TAGS.has(el.tagName.toLowerCase())) {
      el.remove();
      continue;
    }
    for (const attr of Array.from(el.attributes)) {
      const name = attr.name.toLowerCase();
      const value = attr.value.trim().toLowerCase();
      if (name.startsWith("on")) el.removeAttribute(attr.name);
      else if ((name === "href" || name === "src" || name === "xlink:href") && value.startsWith("javascript:"))
        el.removeAttribute(attr.name);
    }
    if (el.tagName.toLowerCase() === "img") {
      const src = el.getAttribute("src") ?? "";
      if (src.startsWith("assets/")) el.setAttribute("src", assetUrl(src.slice("assets/".length)));
      else if (!/^(https?:|data:image\/)/i.test(src)) el.removeAttribute("src");
    }
  }
  // Code callouts ❶–❿ (U+2776–U+277F) need a symbol font that may not be installed: draw them
  // as CSS circles with the plain digit instead.
  for (const el of Array.from(root.querySelectorAll<HTMLElement>(".callout"))) {
    const code = (el.textContent ?? "").trim().codePointAt(0) ?? 0;
    if (code >= 0x2776 && code <= 0x277f) {
      const n = String(code - 0x2775);
      el.textContent = n;
      el.classList.add("callout-num");
      el.setAttribute("aria-label", n);
    }
  }
  return root.innerHTML;
}
