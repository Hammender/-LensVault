export function galleryFaceStatusLabel(needsReview: boolean, matchedPersonId: number | null): string {
  if (needsReview) {
    return "待人工确认";
  }
  return matchedPersonId === null ? "已忽略" : "已确认";
}
