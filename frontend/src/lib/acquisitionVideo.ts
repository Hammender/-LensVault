export function formatVideoTime(seconds: number, precise = false): string {
  const safe = Number.isFinite(seconds) ? Math.max(0, seconds) : 0;
  const milliseconds = Math.floor(safe * 1000 + 0.00001);
  const totalSeconds = Math.floor(milliseconds / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const clock = `${hours ? `${hours.toString().padStart(2, "0")}:` : ""}${minutes.toString().padStart(2, "0")}:${(totalSeconds % 60).toString().padStart(2, "0")}`;
  return precise ? `${clock}.${(milliseconds % 1000).toString().padStart(3, "0")}` : clock;
}

export function parseVideoTime(value: string): number | null {
  const text = value.trim();
  if (!/^\d+(?::\d{1,2}){0,2}(?:\.\d{1,3})?$/.test(text)) return null;
  const parts = text.split(":").map(Number);
  if (parts.length > 1 && parts.slice(1).some((part) => part >= 60)) return null;
  const seconds = parts.reduce((total, part) => total * 60 + part, 0);
  return Number.isFinite(seconds) ? seconds : null;
}

export async function toggleAcquisitionVideoPlayback(
  video: Pick<HTMLVideoElement, "paused" | "currentTime" | "play" | "pause">,
  options: {
    frameTime?: number;
    clearFrame: () => void;
    isCurrent: () => boolean;
    showIndicator: (text: string) => void;
  }
): Promise<void> {
  if (!video.paused) {
    video.pause();
    options.showIndicator("暂停");
    return;
  }
  if (options.frameTime !== undefined) video.currentTime = options.frameTime;
  // 同时取消尚未完成的精确定位，避免结果回来后再次盖住正在播放的视频。
  options.clearFrame();
  try {
    await video.play();
    if (options.isCurrent() && !video.paused) options.showIndicator("播放");
  } catch (cause) {
    if (options.isCurrent() && !(cause instanceof Error && cause.name === "AbortError")) {
      options.showIndicator("无法播放，请重试");
    }
  }
}
