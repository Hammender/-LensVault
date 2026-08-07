import { describe, expect, it } from "vitest";

import {
  availablePhotoPersons,
  availableUploadPersons,
  filterPersonMatches,
  mergePersonIds,
  matchesPersonSearch,
  resolveExistingPerson,
  type SelectablePerson
} from "../src/personPicker";

const persons: SelectablePerson[] = [
  { id: 4, display_name: "张三", is_unknown: false },
  { id: 3, display_name: "王芳", is_unknown: false },
  { id: 2, display_name: "Alice", is_unknown: false },
  { id: 1, display_name: "未知人物", is_unknown: true }
];

describe("人物搜索选择", () => {
  it("支持中文、全拼和拼音首字母搜索", () => {
    expect(matchesPersonSearch("张三", "张三")).toBe(true);
    expect(matchesPersonSearch("张三", "zhangsan")).toBe(true);
    expect(matchesPersonSearch("张三", "zs")).toBe(true);
    expect(matchesPersonSearch("张三", "ls")).toBe(false);
  });

  it("搜索结果保持拼音顺序", () => {
    expect(filterPersonMatches(persons, "").map((person) => person.display_name)).toEqual([
      "Alice",
      "王芳",
      "未知人物",
      "张三"
    ]);
  });

  it("详情候选排除未知人物和已经添加的人物", () => {
    expect(availablePhotoPersons(persons, [{ person_id: 3 }]).map((person) => person.id)).toEqual([2, 4]);
  });

  it("上传多选候选排除未知人物和所有已选项", () => {
    expect(availableUploadPersons(persons, [2, 3]).map((person) => person.id)).toEqual([4]);
  });

  it("批量套用合并人物并保持去重", () => {
    expect(mergePersonIds([2, 3], [3, 4, 4])).toEqual([2, 3, 4]);
  });

  it("仅选中项或精确名称可解析为人物", () => {
    expect(resolveExistingPerson(persons, "其他输入", "4")?.id).toBe(4);
    expect(resolveExistingPerson(persons, " alice ", "")?.id).toBe(2);
    expect(resolveExistingPerson(persons, "zhangsan", "")).toBeNull();
    expect(resolveExistingPerson(persons, "张", "")).toBeNull();
    expect(resolveExistingPerson(persons, "不存在的人", "")).toBeNull();
  });
});
