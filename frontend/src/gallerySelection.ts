export function toggleGalleryPhotoSelection(selectedIds: number[], photoId: number): number[] {
  return selectedIds.includes(photoId)
    ? selectedIds.filter((id) => id !== photoId)
    : [...selectedIds, photoId];
}

export function selectGalleryPage(selectedIds: number[], pageIds: number[]): number[] {
  return Array.from(new Set([...selectedIds, ...pageIds]));
}

export function deselectGalleryPage(selectedIds: number[], pageIds: number[]): number[] {
  const pageIdSet = new Set(pageIds);
  return selectedIds.filter((id) => !pageIdSet.has(id));
}

export function isGalleryPageSelected(selectedIds: number[], pageIds: number[]): boolean {
  return pageIds.length > 0 && pageIds.every((id) => selectedIds.includes(id));
}

export function selectGalleryPhotoRange(
  selectedIds: number[],
  pageIds: number[],
  fromId: number | null,
  targetId: number
): number[] {
  if (fromId === null || !pageIds.includes(fromId) || !pageIds.includes(targetId)) {
    return Array.from(new Set([...selectedIds, targetId]));
  }
  const fromIndex = pageIds.indexOf(fromId);
  const targetIndex = pageIds.indexOf(targetId);
  const minIndex = Math.min(fromIndex, targetIndex);
  const maxIndex = Math.max(fromIndex, targetIndex);
  const rangeIds = pageIds.slice(minIndex, maxIndex + 1);
  return Array.from(new Set([...selectedIds, ...rangeIds]));
}
