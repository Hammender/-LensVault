import { describe, expect, it } from "vitest";

import {
  deselectGalleryPage,
  isGalleryPageSelected,
  selectGalleryPage,
  toggleGalleryPhotoSelection
} from "../src/gallerySelection";

describe("图库跨页选择", () => {
  it("切换单张图片时保留其他页的选择", () => {
    expect(toggleGalleryPhotoSelection([1, 21], 2)).toEqual([1, 21, 2]);
    expect(toggleGalleryPhotoSelection([1, 21], 1)).toEqual([21]);
  });

  it("选中本页时合并并去重", () => {
    expect(selectGalleryPage([1, 21], [1, 2, 3])).toEqual([1, 21, 2, 3]);
  });

  it("取消本页时不影响其他页", () => {
    expect(deselectGalleryPage([1, 2, 21], [1, 2, 3])).toEqual([21]);
  });

  it("仅当本页所有图片均已选中时返回 true", () => {
    expect(isGalleryPageSelected([1, 2, 21], [1, 2])).toBe(true);
    expect(isGalleryPageSelected([1, 21], [1, 2])).toBe(false);
    expect(isGalleryPageSelected([], [])).toBe(false);
  });
});
