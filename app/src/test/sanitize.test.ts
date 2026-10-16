import { isAssetName, sanitizeEngineHtml } from "../lib/sanitize";

const clean = (html: string) => sanitizeEngineHtml(html);

describe("sanitizeEngineHtml", () => {
  it("drops scripts and event handlers, keeps engine attributes", () => {
    const out = clean(`<p data-block="0-1" data-s="2" onclick="x()">a<script>alert(1)</script></p><iframe src="x"></iframe>`);
    expect(out).toContain('data-block="0-1"');
    expect(out).toContain('data-s="2"');
    expect(out).not.toContain("script");
    expect(out).not.toContain("onclick");
    expect(out).not.toContain("iframe");
  });

  it("keeps the engine's structural markup", () => {
    const html =
      '<main><h2 class="b-heading">T</h2><figure><img src="assets/p001_b0.png" alt="Şekil"><figcaption>F</figcaption></figure>' +
      '<ol start="6"><li value="6">x</li></ol><pre><code>a &lt; b</code></pre>' +
      '<p><ruby>word<rt>kelime</rt></ruby></p><aside class="footnotes"><p>n</p></aside></main>';
    const out = clean(html);
    for (const part of ["<main>", "<h2", "<figure>", "<figcaption>", 'start="6"', 'value="6"', "<pre><code>a &lt; b</code></pre>", "<ruby>", "<rt>kelime</rt>", "<aside"]) {
      expect(out).toContain(part);
    }
  });

  it("turns engine asset images into data-asset without any URL", () => {
    const out = clean(`<img src="assets/p094_b0_ab12cd34.png" alt="x"><img src="file:///etc/passwd"><img src="http://127.0.0.1:1/x.png">`);
    expect(out).toContain('data-asset="p094_b0_ab12cd34.png"');
    expect(out).not.toContain("src=");
    expect(out).not.toContain("passwd");
  });

  it("ignores data-asset coming from the input and invalid asset names", () => {
    expect(clean(`<img data-asset="../../secret.png">`)).not.toContain("data-asset");
    expect(clean(`<img src="assets/../x.png">`)).not.toContain("data-asset");
    expect(isAssetName("p001_b0.png")).toBe(true);
    expect(isAssetName("../x.png")).toBe(false);
  });

  it.each([
    `<a href="javascript:alert(1)">x</a>`,
    `<a href="java\tscript:alert(1)">x</a>`,
    `<a href="java&#10;script:alert(1)">x</a>`,
    `<img src="javascript:alert(1)">`,
    `<svg><a xlink:href="javascript:alert(1)"><text>x</text></a></svg>`,
    `<math><mtext><table><mglyph><style><img src=x onerror=alert(1)>`,
  ])("removes javascript: and foreign-content vectors: %s", (html) => {
    const out = clean(html).toLowerCase();
    expect(out).not.toMatch(/javascript|onerror|<svg|<math|<a /);
  });

  it("is safe against the noscript/template mXSS round trip", () => {
    const vectors = [
      `<noscript><p title="</noscript><img src=x onerror=alert(1)>">`,
      `<template><img src=x onerror=alert(1)></template>`,
      `<form><math><mtext></form><form><mglyph><style></math><img src onerror=alert(1)>`,
    ];
    for (const v of vectors) {
      const once = clean(v);
      // Re-inserting the output (as dangerouslySetInnerHTML does) must stay inert.
      const host = document.createElement("div");
      host.innerHTML = once;
      expect(host.querySelector("[onerror]")).toBeNull();
      expect(host.querySelector("noscript, template, style, form")).toBeNull();
      expect(clean(host.innerHTML)).toBe(host.innerHTML);
    }
  });

  it("keeps only the engine's font-size style (rule 4) and drops any other CSS", () => {
    expect(clean('<p style="font-size: calc(var(--scale) * 10.5pt)">a</p>')).toContain("font-size: calc(var(--scale) * 10.5pt)");
    expect(clean('<p style="background:url(http://evil)">a</p>')).not.toContain("style");
    expect(clean('<p style="font-size: calc(var(--scale) * 10pt); position:fixed">a</p>')).not.toContain("style");
  });

  it("keeps escaped text escaped", () => {
    expect(clean(`<p>&lt;script&gt;</p>`)).toBe("<p>&lt;script&gt;</p>");
  });
});

describe("callouts", () => {
  it("turns ❶–❿ into a CSS-drawn digit", () => {
    const out = clean('<pre><code>x <span class="callout">❸</span></code></pre>');
    expect(out).toContain('class="callout callout-num"');
    expect(out).toContain(">3</span>");
    expect(out).not.toContain("❸");
  });
});
