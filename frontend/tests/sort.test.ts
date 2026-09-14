import { describe, expect, it } from "vitest";

import { sortByPinyin } from "../src/lib/sort";

describe("pinyin sorting", () => {
  it("sorts Chinese display names by pinyin and mixes English names alphabetically", () => {
    const people = [
      { id: 6, display_name: "张伟" },
      { id: 5, display_name: "王芳" },
      { id: 4, display_name: "李雷" },
      { id: 3, display_name: "陈默" },
      { id: 2, display_name: "安娜" },
      { id: 1, display_name: "Alice" }
    ];

    expect(sortByPinyin(people, (person) => person.display_name).map((person) => person.display_name)).toEqual([
      "Alice",
      "安娜",
      "陈默",
      "李雷",
      "王芳",
      "张伟"
    ]);
  });

  it("uses ids as a stable tie breaker", () => {
    const people = [
      { id: 2, display_name: "Alice" },
      { id: 1, display_name: "alice" }
    ];

    expect(sortByPinyin(people, (person) => person.display_name).map((person) => person.id)).toEqual([1, 2]);
  });
});
