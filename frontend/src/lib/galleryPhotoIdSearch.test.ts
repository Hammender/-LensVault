import { describe, expect, it } from "vitest";
import { parseGalleryPhotoIdQuery, resolveActivePhotoIdSearch } from "./galleryPhotoIdSearch";

describe("展示图编号搜索解析", () => {
  it("空输入视为未搜索", () => {
    expect(parseGalleryPhotoIdQuery("")).toEqual({ kind: "empty" });
    expect(parseGalleryPhotoIdQuery("   ")).toEqual({ kind: "empty" });
  });

  it("支持纯数字和 # 前缀，并忽略首尾空格", () => {
    expect(parseGalleryPhotoIdQuery("123")).toEqual({ kind: "valid", photoId: 123 });
    expect(parseGalleryPhotoIdQuery("#123")).toEqual({ kind: "valid", photoId: 123 });
    expect(parseGalleryPhotoIdQuery("  # 42 ")).toEqual({ kind: "valid", photoId: 42 });
    expect(parseGalleryPhotoIdQuery("007")).toEqual({ kind: "valid", photoId: 7 });
  });

  it("拒绝非数字、小数、负数和 0", () => {
    for (const value of ["abc", "12a", "1.5", "-3", "#", "##1", "0", "#0"]) {
      expect(parseGalleryPhotoIdQuery(value).kind).toBe("invalid");
    }
  });

  it("拒绝超出数据库整数范围的编号", () => {
    expect(parseGalleryPhotoIdQuery("2147483647")).toEqual({ kind: "valid", photoId: 2147483647 });
    expect(parseGalleryPhotoIdQuery("2147483648").kind).toBe("invalid");
    expect(parseGalleryPhotoIdQuery("3000000000").kind).toBe("invalid");
  });

  it("只有合法编号才保持搜索生效，非法或空输入都会清除已生效的搜索", () => {
    expect(resolveActivePhotoIdSearch(parseGalleryPhotoIdQuery("#123"))).toBe(123);
    expect(resolveActivePhotoIdSearch(parseGalleryPhotoIdQuery("12a"))).toBeNull();
    expect(resolveActivePhotoIdSearch(parseGalleryPhotoIdQuery(""))).toBeNull();
  });
});
