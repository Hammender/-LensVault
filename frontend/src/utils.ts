import type { VideoDetail } from "./types";
import type { WorkspacePermissionsPayload } from "./api";

export const videoPartSize = 16 * 1024 * 1024;
export const videoResumeStorageKey = "pictureshow-video-upload-session";
export const videoUploadQueueStorageKey = "pictureshow-video-upload-queue";
export const videoPartUploadMaxAttempts = 4;
export const videoPartUploadRetryDelayMs = 1200;
export const videoSeekSeconds = 10;
export const videoSeekLargeSeconds = 30;
export const videoLongPressDelayMs = 300;
export const videoLongPressRate = 3;
export const supportedVideoExtensions = [".mp4", ".mkv", ".mov", ".webm"];
export const supportedVideoAccept = "video/mp4,video/x-matroska,video/quicktime,video/webm,.mp4,.mkv,.mov,.webm";
export const supportedVideoFormatLabel = "MP4/MKV/MOV/WEBM";

export const workspacePermissionFields: Array<{ key: keyof WorkspacePermissionsPayload; label: string }> = [
  { key: "can_add_gallery", label: "新增展示图" },
  { key: "can_delete_gallery", label: "删除展示图" },
  { key: "can_edit_gallery", label: "修改展示图" },
  { key: "can_add_samples", label: "新增样本图" },
  { key: "can_delete_samples", label: "删除样本图" },
  { key: "can_edit_samples", label: "修改样本图" },
  { key: "can_add_videos", label: "新增视频" },
  { key: "can_delete_videos", label: "删除视频" },
  { key: "can_edit_videos", label: "修改视频" }
];

export const emptyWorkspacePermissions: WorkspacePermissionsPayload = Object.fromEntries(
  workspacePermissionFields.map((item) => [item.key, false])
) as WorkspacePermissionsPayload;

export function formatDate(value: string | null | undefined): string {
  if (!value) {
    return "未记录时间";
  }
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}

export function formatBytes(value: number): string {
  if (value < 1024) {
    return `${value} B`;
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(1)} KB`;
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(1)} MB`;
  }
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`;
}

export function formatDurationSeconds(value: number | null | undefined): string {
  if (!value || !Number.isFinite(value)) {
    return "时长未知";
  }
  const total = Math.max(0, Math.floor(value));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

export function formatResolution(width: number | null | undefined, height: number | null | undefined): string {
  if (!width || !height) {
    return "分辨率未知";
  }
  return `${width}x${height}`;
}

export function formatCodecs(
  videoCodec: string | null | undefined,
  audioCodec: string | null | undefined,
  status?: string
): string {
  const pending = status === "uploaded" || status === "processing";
  const video = videoCodec || (pending ? "识别中" : "未知视频编码");
  const audio = audioCodec || (pending ? "识别中" : "无音频/未知音频");
  return `${video} / ${audio}`;
}

export function getFileExtension(filename: string): string {
  const match = filename.toLowerCase().match(/\.[^.]+$/);
  return match?.[0] ?? "";
}

export function getVideoFormatLabel(filename: string): string {
  const extension = getFileExtension(filename);
  return extension ? extension.slice(1).toUpperCase() : "VIDEO";
}

export function isSupportedVideoFile(filename: string): boolean {
  return supportedVideoExtensions.includes(getFileExtension(filename));
}

export function isVideoCodecMissing(video: VideoDetail): boolean {
  return video.status === "ready" && (!video.original_video_codec || !video.video_codec);
}

export function isVideoMetadataRepairPending(video: VideoDetail): boolean {
  return (
    isVideoCodecMissing(video) ||
    (
      video.status === "processing_failed" &&
      Boolean(video.processing_error?.includes("UNIQUE constraint failed: video_items.filename, video_items.size_bytes"))
    )
  );
}

export function isTextEditingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

export function videoStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "等待优化",
    processing: "优化中",
    ready: "可播放",
    processing_failed: "优化失败"
  };
  return labels[status] ?? status;
}

export function subtitleTrackStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    pending: "排队中",
    running: "生成中",
    ready: "可用",
    failed: "失败",
    canceled: "已取消"
  };
  return labels[status] ?? status;
}

export function subtitleServiceStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    running: "运行中",
    stopped: "未运行",
    unhealthy: "异常"
  };
  return labels[status] ?? status;
}

export function subtitleAsrStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    not_loaded: "未加载",
    waiting: "等待中",
    loading: "加载中",
    transcribing: "识别中",
    ready: "已就绪",
    error: "异常"
  };
  return labels[status] ?? status;
}

export function splitCommaList(input: string): string[] {
  return Array.from(
    new Set(
      input
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

export function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export function withImageWidth(url: string, width: number): string {
  const next = new URL(url, window.location.origin);
  next.searchParams.set("width", String(width));
  return next.pathname + next.search;
}

export function toWorkspacePermissions(source: Record<string, boolean> | WorkspacePermissionsPayload): WorkspacePermissionsPayload {
  return Object.fromEntries(
    workspacePermissionFields.map((item) => [item.key, Boolean(source[item.key])])
  ) as WorkspacePermissionsPayload;
}
