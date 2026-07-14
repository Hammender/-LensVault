export type PageKey = "home" | "gallery" | "similarity" | "people" | "upload" | "videos" | "statistics" | "video-play";

export function pageFromHash(hash: string): PageKey {
  const value = hash.replace(/^#\/?/, "");
  if (value.startsWith("video-play/")) {
    return "video-play";
  }
  if (value === "people" || value === "upload" || value === "videos" || value === "statistics" || value === "gallery" || value === "similarity") {
    return value;
  }
  return "home";
}

export function routeFromHash(): PageKey {
  return pageFromHash(window.location.hash);
}

export function setRoute(page: PageKey): void {
  window.location.hash = `/${page}`;
}
