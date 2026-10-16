import { parsePageSpec, stopReasonText } from "../lib/format";

describe("parsePageSpec", () => {
  it("parses ranges and lists", () => {
    expect(parsePageSpec("1-3, 5,3", 10)).toEqual([1, 2, 3, 5]);
  });
  it.each(["0", "11", "5-3", "a", ""])("rejects %s", (s) => {
    expect(() => parsePageSpec(s, 10)).toThrow();
  });
});

describe("stopReasonText", () => {
  it("translates known engine reasons and passes others through", () => {
    expect(stopReasonText("pause requested")).toBe("Duraklatma istendi.");
    expect(stopReasonText("budget $2.0000 would be exceeded (spent $1.9000 + next batch ≈ $0.2000)")).toBe(
      "Bütçe sınırı ($2.0000) aşılacaktı: harcanan $1.9000 + sonraki batch ≈ $0.2000.",
    );
    expect(stopReasonText("3 consecutive provider errors; last: boom")).toBe(
      "Üst üste 3 sağlayıcı hatası; sonuncusu: boom",
    );
    expect(stopReasonText("Kullanım limiti")).toBe("Kullanım limiti");
  });
});
