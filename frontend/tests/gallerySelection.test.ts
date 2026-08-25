import { describe, expect, it } from "vitest";

import {
  deselectGalleryPage,
  isGalleryPageSelected,
  selectGalleryPage,
  selectGalleryPhotoRange,
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

  it("Shift 范围连选：正向、反向与空起点处理", () => {
    const pageIds = [10, 11, 12, 13, 14, 15];
    // 无起点时直接选中目标
    expect(selectGalleryPhotoRange([], pageIds, null, 12)).toEqual([12]);

    // 正向连选 10 到 13
    expect(selectGalleryPhotoRange([10], pageIds, 10, 13)).toEqual([10, 11, 12, 13]);

    // 反向连选 14 到 11
    expect(selectGalleryPhotoRange([14, 99], pageIds, 14, 11)).toEqual([14, 99, 11, 12, 13]);

    // 起点不在当前页时直接选中目标
    expect(selectGalleryPhotoRange([99], pageIds, 99, 12)).toEqual([99, 12]);
  });
});
