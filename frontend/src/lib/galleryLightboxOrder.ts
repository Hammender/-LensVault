export type GalleryCardPosition = {
  id: number;
  top: number;
  left: number;
};

/** 按实际卡片顶部从上到下阅读，同一像素高度从左到右。 */
export function sortGalleryLightboxPositions(positions: readonly GalleryCardPosition[]): number[] {
  return [...positions]
    .sort((a, b) => Math.round(a.top) - Math.round(b.top) || a.left - b.left)
    .map((position) => position.id);
}

/** 只接受完整且无重复的当前页顺序，避免测量遗漏造成灯箱漏图。 */
export function isGalleryLightboxOrderValid(
  order: readonly number[],
  photos: readonly { id: number }[],
): boolean {
  const ids = new Set(order);
  const photoIds = new Set(photos.map((photo) => photo.id));
  return order.length === photos.length && ids.size === order.length
    && photoIds.size === photos.length
    && photos.every((photo) => ids.has(photo.id));
}

export function readGalleryLightboxOrder(container: HTMLElement): number[] {
  const origin = container.getBoundingClientRect();
  const positions = Array.from(container.querySelectorAll<HTMLElement>("[data-gallery-photo-id]"))
    .map((card) => {
      const rect = card.getBoundingClientRect();
      return {
        id: Number(card.dataset.galleryPhotoId),
        top: rect.top - origin.top,
        left: rect.left - origin.left,
      };
    });
  return sortGalleryLightboxPositions(positions);
}

/** 每次打开灯箱重新创建；历史页只保留 ID，不保留图片或 DOM。 */
export class GalleryLightboxPageOrders {
  private pages = new Map<number, readonly number[]>();

  resolve(offset: number, measuredOrder: readonly number[], photos: readonly { id: number }[]): readonly number[] {
    const saved = this.pages.get(offset);
    if (saved) {
      if (!isGalleryLightboxOrderValid(saved, photos)) {
        throw new Error("图库内容已变化，请重新打开大图浏览。");
      }
      return saved;
    }
    if (!isGalleryLightboxOrderValid(measuredOrder, photos)) {
      throw new Error("无法确定图片展示顺序，请重新打开大图浏览。");
    }
    const order = [...measuredOrder];
    this.pages.set(offset, order);
    return order;
  }

  get(offset: number): readonly number[] | undefined {
    return this.pages.get(offset);
  }
}
