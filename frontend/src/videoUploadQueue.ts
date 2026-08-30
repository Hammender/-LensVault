import {
  videoPartSize,
  videoUploadQueueStorageKey
} from "./utils";

export type VideoUploadQueueStatus = "queued" | "uploading" | "finalizing" | "completed" | "failed" | "needs_file";

export type VideoUploadQueueItem = {
  id: string;
  filename: string;
  size: number;
  lastModified: number;
  contentType: string | null;
  title: string;
  description: string;
  categoryTagIds: number[];
  categoryTagNames: string[];
  personIds: number[];
  generateZhSubtitles: boolean;
  videoType: "short" | "long" | null;
  sessionId: string | null;
  partSize: number;
  totalParts: number;
  uploadedParts: number[];
  progress: number;
  status: VideoUploadQueueStatus;
  error: string | null;
  completedVideoId: number | null;
};

export type VideoUploadQueueAction =
  | { type: "replace"; items: VideoUploadQueueItem[] }
  | { type: "update"; itemId: string; patch: Partial<VideoUploadQueueItem> }
  | { type: "remove_completed" };

export function videoFileFingerprint(file: File): string {
  return `${file.name}::${file.size}::${file.lastModified}`;
}

export function makeVideoQueueItem(
  file: File,
  options: {
    title: string;
    description: string;
    categoryTagIds: number[];
    categoryTagNames: string[];
    personIds: number[];
    generateZhSubtitles: boolean;
    videoType?: "short" | "long" | null;
  }
): VideoUploadQueueItem {
  return {
    id: videoFileFingerprint(file),
    filename: file.name,
    size: file.size,
    lastModified: file.lastModified,
    contentType: file.type || null,
    title: options.title,
    description: options.description,
    categoryTagIds: [...options.categoryTagIds],
    categoryTagNames: [...options.categoryTagNames],
    personIds: [...options.personIds],
    generateZhSubtitles: options.generateZhSubtitles,
    videoType: options.videoType ?? null,
    sessionId: null,
    partSize: videoPartSize,
    totalParts: Math.max(1, Math.ceil(file.size / videoPartSize)),
    uploadedParts: [],
    progress: 0,
    status: "queued",
    error: null,
    completedVideoId: null
  };
}

export function normalizeVideoQueueItem(source: Partial<VideoUploadQueueItem>): VideoUploadQueueItem | null {
  if (!source.id || !source.filename || typeof source.size !== "number" || typeof source.lastModified !== "number") {
    return null;
  }
  const uploadedParts = Array.isArray(source.uploadedParts)
    ? source.uploadedParts.filter((part): part is number => Number.isInteger(part) && part >= 0)
    : [];
  const totalParts = typeof source.totalParts === "number" && source.totalParts > 0
    ? source.totalParts
    : Math.max(1, uploadedParts.length);
  const status: VideoUploadQueueStatus =
    source.status === "completed" ? "completed"
      : source.status === "failed" ? "failed"
        : source.status === "finalizing" || (source.progress ?? 0) >= 100 ? "finalizing"
          : "needs_file";
  return {
    id: source.id,
    filename: source.filename,
    size: source.size,
    lastModified: source.lastModified,
    contentType: source.contentType ?? null,
    title: source.title ?? source.filename.replace(/\.[^.]+$/, ""),
    description: source.description ?? "",
    categoryTagIds: Array.isArray(source.categoryTagIds)
      ? source.categoryTagIds.filter((id): id is number => Number.isInteger(id))
      : [],
    categoryTagNames: Array.isArray(source.categoryTagNames)
      ? source.categoryTagNames.filter((name): name is string => typeof name === "string")
      : [],
    personIds: Array.isArray(source.personIds)
      ? source.personIds.filter((id): id is number => Number.isInteger(id))
      : [],
    generateZhSubtitles: Boolean(source.generateZhSubtitles),
    videoType: source.videoType === "short" || source.videoType === "long" ? source.videoType : null,
    sessionId: source.sessionId ?? null,
    partSize: typeof source.partSize === "number" && source.partSize > 0 ? source.partSize : videoPartSize,
    totalParts,
    uploadedParts,
    progress: typeof source.progress === "number"
      ? Math.min(100, Math.max(0, source.progress))
      : Math.round((uploadedParts.length / totalParts) * 100),
    status,
    error: status === "needs_file"
      ? "浏览器刷新已中断上传，请重新选择这个原视频文件后继续。"
      : status === "finalizing" ? null : source.error ?? null,
    completedVideoId: typeof source.completedVideoId === "number" ? source.completedVideoId : null
  };
}

export function loadStoredVideoUploadQueue(storage: Storage = window.localStorage): VideoUploadQueueItem[] {
  try {
    const raw = storage.getItem(videoUploadQueueStorageKey);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map((item) => normalizeVideoQueueItem(item as Partial<VideoUploadQueueItem>))
      .filter((item): item is VideoUploadQueueItem => Boolean(item));
  } catch {
    storage.removeItem(videoUploadQueueStorageKey);
    return [];
  }
}

export function saveStoredVideoUploadQueue(
  queue: VideoUploadQueueItem[],
  storage: Storage = window.localStorage
): void {
  const visibleQueue = queue.filter((item) => item.status !== "completed");
  if (visibleQueue.length === 0) {
    storage.removeItem(videoUploadQueueStorageKey);
    return;
  }
  storage.setItem(videoUploadQueueStorageKey, JSON.stringify(visibleQueue));
}

export function videoUploadQueueReducer(
  state: VideoUploadQueueItem[],
  action: VideoUploadQueueAction
): VideoUploadQueueItem[] {
  switch (action.type) {
    case "replace":
      return action.items;
    case "update":
      return state.map((item) => item.id === action.itemId ? { ...item, ...action.patch } : item);
    case "remove_completed":
      return state.filter((item) => item.status !== "completed");
    default:
      return state;
  }
}

export function videoQueueStatusLabel(status: VideoUploadQueueStatus): string {
  const labels: Record<VideoUploadQueueStatus, string> = {
    queued: "待上传",
    uploading: "上传中",
    finalizing: "正在入库/优化",
    completed: "已完成",
    failed: "失败",
    needs_file: "需重选文件"
  };
  return labels[status];
}
