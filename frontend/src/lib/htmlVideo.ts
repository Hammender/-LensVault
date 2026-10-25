export function releaseHtmlVideo(video: HTMLVideoElement | null): void {
  if (!video) return;
  video.pause();
  video.removeAttribute("src");
  video.load();
}

export function htmlVideoHasAddress(video: HTMLVideoElement): boolean {
  return Boolean(video.getAttribute("src") || video.currentSrc);
}

export function waitForHtmlVideoRelease(video: HTMLVideoElement | null, timeoutMs = 800): Promise<void> {
  if (!video) return Promise.resolve();
  return new Promise((resolve) => {
    const finish = () => {
      window.clearTimeout(timer);
      video.removeEventListener("emptied", finish);
      video.removeEventListener("abort", finish);
      resolve();
    };
    const timer = window.setTimeout(finish, timeoutMs);
    video.addEventListener("emptied", finish);
    video.addEventListener("abort", finish);
    if (video.networkState === HTMLMediaElement.NETWORK_EMPTY && !video.getAttribute("src")) {
      queueMicrotask(finish);
    }
  });
}
