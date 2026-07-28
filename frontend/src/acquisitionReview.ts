export const acquisitionAssetPageSize = 60;

export type AcquisitionLightboxShortcut = "toggle_selection" | "reject";

export function getAcquisitionLightboxShortcut(key: string): AcquisitionLightboxShortcut | null {
  if (key === " ") return "toggle_selection";
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
