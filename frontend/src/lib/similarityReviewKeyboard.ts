export type SimilarityLightboxShortcut = "toggle_selection" | "delete_current" | "previous_group" | "next_group" | "dismiss_group" | null;

export function getSimilarityLightboxShortcut(key: string): SimilarityLightboxShortcut {
  if (key === " " || key === "Spacebar") return "toggle_selection";
  if (key === "Delete") return "delete_current";
  if (key === "ArrowUp") return "previous_group";
  if (key === "ArrowDown") return "next_group";
  if (key === "p" || key === "P") return "dismiss_group";
  return null;
}

export function findPreviewAfterCurrentDelete(photoIds: number[], currentPhotoId: number): number | null {
  const currentIndex = photoIds.indexOf(currentPhotoId);
  if (currentIndex < 0) return null;
  return photoIds[currentIndex + 1] ?? photoIds[currentIndex - 1] ?? null;
}
