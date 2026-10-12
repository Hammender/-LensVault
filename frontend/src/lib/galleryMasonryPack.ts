/**
 * 展示图库瀑布流「智能装箱」（仅作用于当前页的展示顺序）。
 *
 * 算法简述：
 * 1. 用 width/height 估算每张图在单位列宽下的相对高度 h = 1 / aspectRatio（缺尺寸时按竖图 3:4）；
 *    图文卡（is_rich_text）按约 4:3 预览 + 文案区估为 1.15，贴近 .rich-card-layout 渲染。
 * 2. 先按相对高度降序（同等高度保持原相对次序），减少矮图先入导致的前排空洞。
 * 3. 贪心放入当前累计高度最短的一列（shortest-column bin packing）。
 *
 * 不修改服务端排序与分页总数；换页后重新装箱。导出/选择仍按 photo.id。
 * Shift 框选请使用 flattenGalleryMasonryVisualOrder（列优先：左→右、列内上→下），与 DOM 一致。
 * 灯箱左右翻页仍按接口返回的 galleryPhotos 顺序，与瀑布流展示顺序无关。
 */

export type MasonryPackInput = {
  id: number;
  width: number | null;
  height: number | null;
  is_rich_text?: boolean;
};

export function galleryPhotoAspectRatio(width: number | null, height: number | null): number {
  if (width && height && width > 0 && height > 0) {
    return width / height;
  }
  return 3 / 4;
}

/** 单位列宽下的相对高度；图文卡单独估算以贴近真实卡片。 */
export function galleryPhotoRelativeHeight(
  width: number | null,
  height: number | null,
  isRichText = false,
): number {
  if (isRichText) {
    // 约等于 4:3 图（0.75）+ 文案/内边距区，对齐 styles 中图文卡大致比例
    return 1.15;
  }
  return 1 / galleryPhotoAspectRatio(width, height);
}

export function resolveGalleryColumnCount(containerWidth: number): number {
  if (containerWidth >= 1500) return 5;
  if (containerWidth >= 1180) return 4;
  if (containerWidth >= 820) return 3;
  if (containerWidth >= 520) return 2;
  return 1;
}

export function packGalleryMasonryPage<T extends MasonryPackInput>(
  items: readonly T[],
  columnCount: number,
): T[][] {
  if (items.length === 0) {
    return [];
  }
  const cols = Math.max(1, Math.floor(columnCount));
  const columns: T[][] = Array.from({ length: cols }, () => []);
  const heights = Array.from({ length: cols }, () => 0);

  const ranked = items
    .map((item, index) => ({
      item,
      index,
      height: galleryPhotoRelativeHeight(item.width, item.height, Boolean(item.is_rich_text)),
    }))
    .sort((a, b) => b.height - a.height || a.index - b.index);

  for (const entry of ranked) {
    let target = 0;
    for (let i = 1; i < cols; i += 1) {
      if (heights[i] < heights[target]) {
        target = i;
      }
    }
    columns[target].push(entry.item);
    heights[target] += entry.height;
  }
  return columns;
}

/** 瀑布流视觉顺序：列从左到右，列内从上到下（与 DOM 一致），供 Shift 范围选择。 */
export function flattenGalleryMasonryVisualOrder<T extends { id: number }>(
  columns: readonly (readonly T[])[],
): number[] {
  return columns.flatMap((column) => column.map((item) => item.id));
}

export function formatGalleryCardPersonNames(
  persons: readonly { person_name: string }[],
): string {
  const names = persons.map((person) => person.person_name.trim()).filter(Boolean);
  return names.length > 0 ? names.join(" · ") : "未标注人物";
}

export function galleryCardNeedsReview(
  persons: readonly { is_unknown: boolean }[],
): boolean {
  return persons.some((person) => person.is_unknown);
}
