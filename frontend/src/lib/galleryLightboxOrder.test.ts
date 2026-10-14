import { describe, expect, it } from "vitest";

import {
  GalleryLightboxPageOrders,
  isGalleryLightboxOrderValid,
  readGalleryLightboxOrder,
  sortGalleryLightboxPositions,
} from "./galleryLightboxOrder";

const page = (ids: readonly number[]) => ids.map((id) => ({ id }));

describe("图库灯箱横向阅读顺序", () => {
  it("按顶部从上到下、同高度从左到右，顺序不受接口 ID 和 DOM 列优先顺序影响", () => {
    const positions = [
      { id: 16, top: 0, left: 0 },
      { id: 2, top: 500, left: 0 },
      { id: 17, top: 0, left: 300 },
      { id: 3, top: 300, left: 300 },
      { id: 1, top: 0, left: 600 },
      { id: 4, top: 400, left: 600 },
    ];
    expect(sortGalleryLightboxPositions(positions)).toEqual([16, 17, 1, 3, 4, 2]);
    expect(positions.map((position) => position.id)).toEqual([16, 2, 17, 3, 1, 4]);
  });

  it("同一像素内的顶部误差不打乱从左到右的顺序", () => {
    expect(sortGalleryLightboxPositions([
      { id: 1, top: 100.1, left: 600 },
      { id: 2, top: 100.2, left: 0 },
      { id: 3, top: 100.15, left: 300 },
      { id: 4, top: 101.2, left: 0 },
    ])).toEqual([2, 3, 1, 4]);
  });

  it("单列和空页均可排序", () => {
    expect(sortGalleryLightboxPositions([])).toEqual([]);
    expect(sortGalleryLightboxPositions([
      { id: 2, top: 500, left: 0 },
      { id: 9, top: 0, left: 0 },
      { id: 1, top: 200, left: 0 },
    ])).toEqual([9, 1, 2]);
  });

  it("采集实际 DOM 位置，包括屏幕外卡片，并抵消滚动偏移", () => {
    const makeContainer = (scroll: number) => ({
      getBoundingClientRect: () => ({ top: 200 - scroll, left: 100 }),
      querySelectorAll: () => [
        { dataset: { galleryPhotoId: "8" }, getBoundingClientRect: () => ({ top: 2200 - scroll, left: 100 }) },
        { dataset: { galleryPhotoId: "16" }, getBoundingClientRect: () => ({ top: 200 - scroll, left: 100 }) },
        { dataset: { galleryPhotoId: "3" }, getBoundingClientRect: () => ({ top: 200 - scroll, left: 400 }) },
      ],
    } as unknown as HTMLElement);
    expect(readGalleryLightboxOrder(makeContainer(0))).toEqual([16, 3, 8]);
    expect(readGalleryLightboxOrder(makeContainer(1000))).toEqual([16, 3, 8]);
  });

  it("拒绝遗漏、重复及混入其他页的 ID", () => {
    const photos = page([1, 2, 3]);
    expect(isGalleryLightboxOrderValid([3, 1, 2], photos)).toBe(true);
    expect(isGalleryLightboxOrderValid([3, 1], photos)).toBe(false);
    expect(isGalleryLightboxOrderValid([3, 1, 1], photos)).toBe(false);
    expect(isGalleryLightboxOrderValid([3, 1, 4], photos)).toBe(false);
    expect(isGalleryLightboxOrderValid([1, 2], page([1, 1]))).toBe(false);
    expect(isGalleryLightboxOrderValid([], [])).toBe(true);
  });
});

describe("图库灯箱会话顺序快照", () => {
  it("视觉第一张是接口第 16 张时，顺序仍完整包含一页的 20 张图片", () => {
    const photos = page(Array.from({ length: 20 }, (_, index) => index + 1));
    const measured = [16, 3, 12, 8, 1, 20, 4, 9, 13, 2, 15, 5, 10, 17, 6, 14, 7, 11, 18, 19];
    const orders = new GalleryLightboxPageOrders();
    const order = orders.resolve(0, measured, photos);
    expect(order[0]).toBe(16);
    expect(order).toEqual(measured);
    expect(new Set(order).size).toBe(20);
    expect([...order].sort((a, b) => a - b)).toEqual(photos.map((photo) => photo.id));
  });

  it("跨页保存各页顺序，回到上一页仍使用原来的末张", () => {
    const orders = new GalleryLightboxPageOrders();
    const first = orders.resolve(0, [3, 1, 2], page([1, 2, 3]));
    const second = orders.resolve(20, [23, 22, 21], page([21, 22, 23]));
    expect(second[0]).toBe(23);
    const previous = orders.resolve(0, [2, 3, 1], page([1, 2, 3]));
    expect(previous).toBe(first);
    expect(previous[previous.length - 1]).toBe(2);
    expect(orders.get(20)).toBe(second);
  });

  it("缩放或文案变化不覆盖快照，重新打开则使用新布局", () => {
    const photos = page([1, 2, 3]);
    const measured = [3, 1, 2];
    const orders = new GalleryLightboxPageOrders();
    orders.resolve(0, measured, photos);
    measured.reverse();
    expect(orders.resolve(0, [1, 2, 3], photos)).toEqual([3, 1, 2]);
    expect(new GalleryLightboxPageOrders().resolve(0, [1, 2, 3], photos)).toEqual([1, 2, 3]);
  });

  it("支持最后不足一页，拒绝列表变化后继续使用过期快照", () => {
    const orders = new GalleryLightboxPageOrders();
    expect(orders.resolve(40, [44], page([44]))).toEqual([44]);
    expect(() => orders.resolve(40, [45], page([45]))).toThrow("图库内容已变化");
    expect(() => orders.resolve(20, [21], page([21, 22]))).toThrow("无法确定图片展示顺序");
    expect(orders.get(20)).toBeUndefined();
  });
});
