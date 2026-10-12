import { describe, expect, it } from "vitest";
import {
  formatGalleryCardPersonNames,
  galleryCardNeedsReview,
  galleryPhotoAspectRatio,
  galleryCardRelativeHeight,
  galleryPhotoRelativeHeight,
  flattenGalleryMasonryVisualOrder,
  packGalleryMasonryPage,
  resolveGalleryColumnCount,
} from "./galleryMasonryPack";

describe("展示图瀑布流智能装箱", () => {
  it("缺尺寸时按竖图 3:4 估算", () => {
    expect(galleryPhotoAspectRatio(null, null)).toBeCloseTo(0.75);
    expect(galleryPhotoRelativeHeight(300, 400)).toBeCloseTo(4 / 3);
  });

  it("按容器宽度选择列数", () => {
    expect(resolveGalleryColumnCount(1600)).toBe(5);
    expect(resolveGalleryColumnCount(1200)).toBe(4);
    expect(resolveGalleryColumnCount(900)).toBe(3);
    expect(resolveGalleryColumnCount(600)).toBe(2);
    expect(resolveGalleryColumnCount(400)).toBe(1);
  });

  it("只重排当前页：结果包含全部 id，且偏向填平各列", () => {
    const page = [
      { id: 1, width: 300, height: 400 },
      { id: 2, width: 600, height: 400 },
      { id: 3, width: 300, height: 500 },
      { id: 4, width: 400, height: 400 },
      { id: 5, width: 300, height: 450 },
      { id: 6, width: 800, height: 400 },
    ];
    const columns = packGalleryMasonryPage(page, 3);
    expect(columns).toHaveLength(3);
    const ids = columns.flat().map((item) => item.id).sort((a, b) => a - b);
    expect(ids).toEqual([1, 2, 3, 4, 5, 6]);

    const heights = columns.map((col) =>
      col.reduce((sum, item) => sum + galleryCardRelativeHeight(item.width, item.height), 0),
    );
    const spread = Math.max(...heights) - Math.min(...heights);
    // 贪心后各列相对高度差应小于「全部塞进一列」的极端情况
    const naive = page.reduce((sum, item) => sum + galleryCardRelativeHeight(item.width, item.height), 0);
    expect(spread).toBeLessThan(naive);
  });

  it("列数为 1 时保持按高度排序后的单列", () => {
    const page = [
      { id: 1, width: 300, height: 300 },
      { id: 2, width: 300, height: 600 },
    ];
    expect(packGalleryMasonryPage(page, 1)[0].map((item) => item.id)).toEqual([2, 1]);
  });

  it("无结果时不生成空列；视觉顺序为列优先展平", () => {
    expect(packGalleryMasonryPage([], 4)).toEqual([]);
    const columns = packGalleryMasonryPage(
      [
        { id: 1, width: 300, height: 400 },
        { id: 2, width: 300, height: 500 },
        { id: 3, width: 300, height: 300 },
      ],
      2,
    );
    expect(flattenGalleryMasonryVisualOrder(columns)).toEqual(columns.flatMap((col) => col.map((item) => item.id)));
  });

  it("图文卡相对高度高于同尺寸普通竖图估算，便于装箱", () => {
    const plain = galleryPhotoRelativeHeight(400, 300, false);
    const rich = galleryPhotoRelativeHeight(400, 300, true);
    expect(rich).toBe(1.15);
    expect(rich).toBeGreaterThan(plain);
  });

  it("姓名用间隔号拼接，未知人物触发待复核标记", () => {
    expect(formatGalleryCardPersonNames([{ person_name: "刘亦菲" }, { person_name: "范冰冰" }])).toBe("刘亦菲 · 范冰冰");
    expect(formatGalleryCardPersonNames([])).toBe("未识别");
    expect(galleryCardNeedsReview([{ is_unknown: false }, { is_unknown: true }])).toBe(true);
    expect(galleryCardNeedsReview([{ is_unknown: false }])).toBe(false);
  });
});
