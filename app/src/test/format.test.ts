import { parsePageSpec } from "../lib/format";

describe("parsePageSpec", () => {
  it("parses ranges and lists", () => {
    expect(parsePageSpec("1-3, 5,3", 10)).toEqual([1, 2, 3, 5]);
  });
  it.each(["0", "11", "5-3", "a", ""])("rejects %s", (s) => {
    expect(() => parsePageSpec(s, 10)).toThrow();
  });
});
