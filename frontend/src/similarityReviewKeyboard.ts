export type SimilarityLightboxShortcut = "toggle_selection" | "delete_current" | null;

export function getSimilarityLightboxShortcut(key: string): SimilarityLightboxShortcut {
  if (key === " " || key === "Spacebar") return "toggle_selection";
  if (key === "Delete") return "delete_current";
  return null;
}

export function findPreviewAfterCurrentDelete(photoIds: number[], currentPhotoId: number): number | null {
  const currentIndex = photoIds.indexOf(currentPhotoId);
  if (currentIndex < 0) return null;
  return photoIds[currentIndex + 1] ?? photoIds[currentIndex - 1] ?? null;
}
