import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

import { GalleryLightboxPageOrders, isGalleryLightboxOrderValid } from "../lib/galleryLightboxOrder";
import type { GalleryPhotoListItem, PaginatedGalleryPhotos } from "../types";

type LightboxState = {
  photo: GalleryPhotoListItem;
  order: readonly number[];
  offset: number;
  total: number;
};

type LayoutRequest = {
  requestId: number;
  photos: GalleryPhotoListItem[];
  offset: number;
};

type Options = {
  photos: GalleryPhotoListItem[];
  offset: number;
  total: number;
  pageSize: number;
  contextKey: string;
  busy: boolean;
  loadPage: (offset: number) => Promise<PaginatedGalleryPhotos | null>;
  commitPage: (page: PaginatedGalleryPhotos) => void;
  onError: (message: string) => void;
};

export function useGalleryLightbox({
  photos, offset, total, pageSize, contextKey, busy, loadPage, commitPage, onError,
}: Options) {
  const [state, setState] = useState<LightboxState | null>(null);
  const activeRef = useRef<LightboxState | null>(null);
  const ordersRef = useRef(new GalleryLightboxPageOrders());
  const generationRef = useRef(0);
  const loadingRef = useRef(false);
  const [navigating, setNavigating] = useState(false);
  const [layoutRequest, setLayoutRequest] = useState<LayoutRequest | null>(null);
  const measurementRef = useRef<{
    requestId: number;
    resolve: (order: number[] | null) => void;
  } | null>(null);

  const close = useCallback(() => {
    generationRef.current += 1;
    measurementRef.current?.resolve(null);
    measurementRef.current = null;
    activeRef.current = null;
    ordersRef.current = new GalleryLightboxPageOrders();
    loadingRef.current = false;
    setState(null);
    setNavigating(false);
    setLayoutRequest(null);
  }, []);

  const cancelNavigation = useCallback(() => {
    if (loadingRef.current) close();
  }, [close]);

  // 切换工作区、筛选或页面后，旧请求不得重新打开灯箱或覆盖新列表。
  useLayoutEffect(() => {
    close();
    return () => {
      generationRef.current += 1;
      measurementRef.current?.resolve(null);
      measurementRef.current = null;
    };
  }, [contextKey, close]);

  useEffect(() => {
    const current = activeRef.current;
    if (!current || loadingRef.current) return;
    if (offset !== current.offset || total !== current.total || !isGalleryLightboxOrderValid(current.order, photos)) {
      close();
    } else {
      const photo = photos.find((item) => item.id === current.photo.id)!;
      if (photo !== current.photo) updateState({ ...current, photo });
    }
  }, [photos, offset, total, close]);

  function updateState(next: LightboxState) {
    activeRef.current = next;
    setState(next);
  }

  function open(photoId: number, visualOrder: readonly number[]) {
    const photo = photos.find((item) => item.id === photoId);
    if (!photo || busy || loadingRef.current) return;
    close();
    try {
      const order = ordersRef.current.resolve(offset, visualOrder, photos);
      updateState({ photo, order, offset, total });
    } catch (cause) {
      onError(cause instanceof Error ? cause.message : "打开大图失败。");
    }
  }

  const completeLayout = useCallback((requestId: number, order: number[]) => {
    const measurement = measurementRef.current;
    if (measurement?.requestId !== requestId || generationRef.current !== requestId) return;
    measurementRef.current = null;
    measurement.resolve(order);
  }, []);

  async function move(direction: -1 | 1) {
    const current = activeRef.current;
    if (!current || busy || loadingRef.current) return;
    const index = current.order.indexOf(current.photo.id);
    const adjacentId = current.order[index + direction];
    if (adjacentId !== undefined) {
      const photo = photos.find((item) => item.id === adjacentId);
      if (photo) updateState({ ...current, photo });
      return;
    }
    const targetOffset = current.offset + direction * pageSize;
    if (targetOffset < 0 || targetOffset >= current.total) return;

    // 同步加锁，阻止 React 下一次渲染之前的重复点击和键盘连发。
    const requestId = ++generationRef.current;
    loadingRef.current = true;
    setNavigating(true);
    const previousPage = { items: photos, offset, total, limit: pageSize };
    let committed = false;
    try {
      const page = await loadPage(targetOffset);
      if (generationRef.current !== requestId || !page) return;
      if (page.items.length === 0) {
        commitPage(page);
        close();
        return;
      }

      let measuredOrder = ordersRef.current.get(page.offset);
      if (page.total !== current.total || (measuredOrder && !isGalleryLightboxOrderValid(measuredOrder, page.items))) {
        commitPage(page);
        close();
        onError("图库内容已变化，请重新打开大图浏览。");
        return;
      }
      if (!measuredOrder) {
        // 先提交目标页，等待图库确认列数并完成布局；期间仍展示原来的大图。
        const measurement = new Promise<number[] | null>((resolve) => {
          measurementRef.current = { requestId, resolve };
        });
        setLayoutRequest({ requestId, photos: page.items, offset: page.offset });
        commitPage(page);
        committed = true;
        const result = await measurement;
        if (generationRef.current !== requestId || !result) return;
        measuredOrder = result;
      }
      const order = ordersRef.current.resolve(page.offset, measuredOrder, page.items);
      const photoId = direction === 1 ? order[0] : order[order.length - 1];
      const photo = page.items.find((item) => item.id === photoId)!;
      if (!committed) commitPage(page);
      updateState({ photo, order, offset: page.offset, total: page.total });
    } catch (cause) {
      if (generationRef.current !== requestId) return;
      if (committed) commitPage(previousPage);
      onError(cause instanceof Error ? cause.message : "翻页失败。");
    } finally {
      if (generationRef.current === requestId) {
        loadingRef.current = false;
        setNavigating(false);
        setLayoutRequest(null);
      }
    }
  }

  const index = state ? state.order.indexOf(state.photo.id) : -1;
  const photo = state && offset === state.offset
    ? photos.find((item) => item.id === state.photo.id) ?? state.photo
    : state?.photo ?? null;
  const hasPrevPage = !!state && state.offset > 0;
  const hasNextPage = !!state && state.offset + pageSize < state.total;
  const isFirstOfPage = index === 0;
  const isLastOfPage = !!state && index === state.order.length - 1;

  return {
    photo, index, offset: state?.offset ?? offset, total: state?.total ?? total,
    navigating, layoutRequest, completeLayout, open, close, cancelNavigation,
    isFirstOfPage, isLastOfPage, hasPrevPage, hasNextPage,
    canGoPrev: !!state && !navigating && (index > 0 || hasPrevPage),
    canGoNext: !!state && !navigating && (!isLastOfPage || hasNextPage),
    goPrevious: () => move(-1),
    goNext: () => move(1),
  };
}
