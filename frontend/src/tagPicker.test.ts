import { describe, expect, it } from "vitest";

import { filterTagMatches, resolveExistingTag, type SelectableTag } from "./tagPicker";

const tags: SelectableTag[] = [
  { id: 1, name: "旅行", is_system: false },
  { id: 2, name: "旅行日记", is_system: false },
  { id: 3, name: "Portrait", is_system: false }
];

describe("标签搜索选择", () => {
  it("按名称进行忽略大小写的包含匹配", () => {
    expect(filterTagMatches(tags, "旅行").map((tag) => tag.id)).toEqual([1, 2]);
    expect(filterTagMatches(tags, "portrait").map((tag) => tag.id)).toEqual([3]);
  });

  it("优先使用已选标签，并支持精确名称解析", () => {
    expect(resolveExistingTag(tags, "已被修改", "2")?.id).toBe(2);
    expect(resolveExistingTag(tags, " portrait ", "")?.id).toBe(3);
  });

  it("不存在或只有部分匹配时不会解析为标签", () => {
    expect(resolveExistingTag(tags, "旅", "")).toBeNull();
    expect(resolveExistingTag(tags, "不存在", "")).toBeNull();
  });
});
