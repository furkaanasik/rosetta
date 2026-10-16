import { initialState, reducer } from "../state";

const book = { id: 1, file_hash: "h", title: "t", page_count: 10, path: "/t.pdf" };

describe("reducer", () => {
  it("clamps page and zoom", () => {
    let s = reducer(initialState, { type: "bookOpened", book, pdfSrc: null });
    s = reducer(s, { type: "goto", page: 99 });
    expect(s.page).toBe(10);
    s = reducer(s, { type: "goto", page: -3 });
    expect(s.page).toBe(1);
    s = reducer(s, { type: "zoom", zoom: 10 });
    expect(s.zoom).toBe(3);
  });

  it("changes view mode", () => {
    expect(reducer(initialState, { type: "mode", mode: "learn" }).mode).toBe("learn");
  });
});
