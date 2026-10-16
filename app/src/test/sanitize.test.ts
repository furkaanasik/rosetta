import { sanitizeEngineHtml } from "../lib/sanitize";

const asset = (n: string) => `http://127.0.0.1:9/api/books/1/assets/${n}?token=t`;

describe("sanitizeEngineHtml", () => {
  it("drops scripts and event handlers", () => {
    const out = sanitizeEngineHtml(
      `<p data-block="0-1" onclick="x()">a<script>alert(1)</script></p><iframe src="x"></iframe>`,
      asset,
    );
    expect(out).toContain('data-block="0-1"');
    expect(out).not.toContain("script");
    expect(out).not.toContain("onclick");
    expect(out).not.toContain("iframe");
  });

  it("rewrites asset images and removes unknown sources", () => {
    const out = sanitizeEngineHtml(`<img src="assets/p094_b0.png"><img src="file:///etc/passwd">`, asset);
    expect(out).toContain('src="http://127.0.0.1:9/api/books/1/assets/p094_b0.png?token=t"');
    expect(out).not.toContain("passwd");
  });

  it("removes javascript: links", () => {
    expect(sanitizeEngineHtml(`<a href="javascript:alert(1)">x</a>`, asset)).not.toContain("javascript");
  });

  it("keeps escaped text escaped", () => {
    expect(sanitizeEngineHtml(`<p>&lt;script&gt;</p>`, asset)).toBe("<p>&lt;script&gt;</p>");
  });
});

describe("callouts", () => {
  it("turns ❶–❿ into a CSS-drawn digit", () => {
    const out = sanitizeEngineHtml('<pre><code>x <span class="callout">❸</span></code></pre>', (n) => n);
    expect(out).toContain('class="callout callout-num"');
    expect(out).toContain(">3</span>");
    expect(out).not.toContain("❸");
  });
});
