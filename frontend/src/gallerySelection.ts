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
