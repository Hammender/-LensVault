import { describe, expect, it } from "vitest";

import type { Person } from "../types";
import { filterPeopleByTag } from "./peopleTags";

const person = (id: number, name: string, tagIds?: number[]): Person => ({
  id, name, display_name: name, is_unknown: false, unknown_serial: null, note: null,
  sample_count: 0, gallery_photo_count: 0, created_at: "2026-10-17T10:00:00+08:00", tag_ids: tagIds
});
const persons = [person(1, "张三", [10, 20]), person(2, "王芳", [10]), person(3, "Alice", []), person(4, "李四")];

describe("按普通标签筛选人物", () => {
  it("只返回直接绑定标签的人物，保留拼音排序", () => {
    expect(filterPeopleByTag(persons, "", "10").map((item) => item.id)).toEqual([2, 1]);
    expect(filterPeopleByTag(persons, "", "20").map((item) => item.id)).toEqual([1]);
  });

  it("标签条件与名称、拼音搜索取交集", () => {
    expect(filterPeopleByTag(persons, "zs", "10").map((item) => item.id)).toEqual([1]);
    expect(filterPeopleByTag(persons, "wangfang", "20")).toEqual([]);
  });

  it("无关联时返回空列表，清除标签条件后恢复全部人物", () => {
    expect(filterPeopleByTag(persons, "", "99")).toEqual([]);
    expect(filterPeopleByTag(persons, "", "").map((item) => item.id)).toEqual([3, 4, 2, 1]);
    expect(persons.map((item) => item.id)).toEqual([1, 2, 3, 4]);
  });
});
