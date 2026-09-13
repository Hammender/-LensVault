export const acquisitionAssetPageSize = 60;

export function getAcquisitionPreviewUrl(
  previewUrl: string,
  maxEdge: number
): string {
  const url = new URL(previewUrl, "http://localhost");
  url.searchParams.set("max_edge", String(maxEdge));
  return `${url.pathname}${url.search}`;
}

export type AcquisitionRejectContinuation =
  | { kind: "local"; index: number }
  | { kind: "reload"; offset: number; preferredIndex: number; direction: -1 | 1 }
  | { kind: "close" };

export type AcquisitionPageFill = { offset: number; limit: number };

export function getAcquisitionPageFill(
  loadedCount: number,
  currentOffset: number,
  remainingTotal: number,
  pageSize = acquisitionAssetPageSize
): AcquisitionPageFill | null {
  const expectedCount = Math.min(pageSize, Math.max(0, remainingTotal - currentOffset));
  const missingCount = Math.max(0, expectedCount - loadedCount);
  return missingCount > 0
    ? { offset: currentOffset + loadedCount, limit: missingCount }
    : null;
}

export function isAcquisitionPageFillValid(
  existingIds: readonly string[],
  remainingTotal: number,
  fill: AcquisitionPageFill,
  fillPage: { offset: number; total: number; items: readonly { id: string }[] }
): boolean {
  const knownIds = new Set(existingIds);
  const fillIds = new Set(fillPage.items.map((asset) => asset.id));
  return fillPage.offset === fill.offset
    && fillPage.total === remainingTotal
    && fillPage.items.length === fill.limit
    && fillIds.size === fillPage.items.length
    && fillPage.items.every((asset) => !knownIds.has(asset.id));
}

export function getAcquisitionRejectContinuation(
  previewableAssets: boolean[],
  removedIndex: number,
  currentOffset: number,
  remainingTotal: number,
  pageSize = acquisitionAssetPageSize
): AcquisitionRejectContinuation {
  for (let index = Math.max(0, removedIndex); index < previewableAssets.length; index += 1) {
    if (previewableAssets[index]) return { kind: "local", index };
  }
  if (remainingTotal <= 0) return { kind: "close" };

  const removedGlobalIndex = currentOffset + removedIndex;
  const hasFollowingAsset = removedGlobalIndex < remainingTotal;
  if (!hasFollowingAsset) {
    for (let index = Math.min(removedIndex - 1, previewableAssets.length - 1); index >= 0; index -= 1) {
      if (previewableAssets[index]) return { kind: "local", index };
    }
  }
  const targetGlobalIndex = hasFollowingAsset ? removedGlobalIndex : remainingTotal - 1;
  const offset = Math.floor(targetGlobalIndex / pageSize) * pageSize;
  return {
    kind: "reload",
    offset,
    preferredIndex: targetGlobalIndex - offset,
    direction: hasFollowingAsset ? 1 : -1
  };
}

export type AcquisitionLightboxShortcut = "toggle_selection" | "reject";

export function getAcquisitionLightboxShortcut(
  key: string,
  mediaType: "image" | "video" = "image"
): AcquisitionLightboxShortcut | null {
  if (key === "Enter") return "toggle_selection";
  if (key === " " && mediaType === "image") return "toggle_selection";
  if (key === "Delete") return "reject";
  return null;
}

export function isAcquisitionImportBatchActive(status: string): boolean {
  return status === "queued" || status === "running";
}

export type AcquisitionPagination = {
  currentPage: number;
  totalPages: number;
  rangeStart: number;
  rangeEnd: number;
};

export type AcquisitionStatusReset = {
  status: string;
  offset: number;
  selectedIds: string[];
  jumpPage: string;
  lightboxAssetId: null;
};

export function createAcquisitionStatusReset(status: string): AcquisitionStatusReset {
  return { status, offset: 0, selectedIds: [], jumpPage: "", lightboxAssetId: null };
}

export function clampAcquisitionOffset(total: number, requestedOffset: number, limit = acquisitionAssetPageSize): number {
  if (total <= 0) return 0;
  const safeOffset = Math.max(0, requestedOffset);
  const lastOffset = Math.floor((total - 1) / limit) * limit;
  return Math.min(Math.floor(safeOffset / limit) * limit, lastOffset);
}

export function getAcquisitionPagination(
  total: number,
  offset: number,
  loadedCount: number,
  limit = acquisitionAssetPageSize
): AcquisitionPagination {
  if (total <= 0) return { currentPage: 0, totalPages: 0, rangeStart: 0, rangeEnd: 0 };
  return {
    currentPage: Math.floor(offset / limit) + 1,
    totalPages: Math.ceil(total / limit),
    rangeStart: offset + 1,
    rangeEnd: Math.min(offset + loadedCount, total)
  };
}

export function toggleAcquisitionSelection(selectedIds: string[], assetId: string): string[] {
  return selectedIds.includes(assetId)
    ? selectedIds.filter((id) => id !== assetId)
    : [...selectedIds, assetId];
}

export function hasSelectedAllAcquisitionAssets(selectedIds: string[], total: number): boolean {
  return total > 0 && selectedIds.length === total;
}

export function removeAcquisitionSelection(selectedIds: string[], processedIds: string[]): string[] {
  const processed = new Set(processedIds);
  return selectedIds.filter((id) => !processed.has(id));
}

export function findClosestPreviewableIndex(
  items: Array<{ preview_url: string | null }>,
  preferredIndex: number
): number {
  for (let index = Math.max(0, preferredIndex); index < items.length; index += 1) {
    if (items[index].preview_url) return index;
  }
  for (let index = Math.min(preferredIndex - 1, items.length - 1); index >= 0; index -= 1) {
    if (items[index].preview_url) return index;
  }
  return -1;
}

export function getNextAcquisitionSnapshotIndex(
  snapshotIds: readonly string[],
  currentIndex: number,
  direction: -1 | 1,
  unavailableIds: ReadonlySet<string>
): number {
  for (let index = currentIndex + direction; index >= 0 && index < snapshotIds.length; index += direction) {
    if (!unavailableIds.has(snapshotIds[index])) return index;
  }
  return -1;
}
