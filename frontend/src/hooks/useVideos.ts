import { useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";

import {
  addVideoCategoryTag,
  addVideoPerson,
  cancelVideoSubtitles,
  cancelVideoUpload,
  completeVideoUpload,
  createVideoCategoryTag,
  createVideoPerson,
  createVideoUploadSession,
  deleteVideo,
  deleteVideoCategoryTag,
  deleteVideoPerson,
  generateVideoSubtitles,
  getSubtitleServiceLogs,
  getSubtitleServiceStatus,
  getVideo,
  getVideoPlaybackDiagnostics,
  getVideoUploadSession,
  listSubtitleJobs,
  listVideoCategoryTags,
  listVideoPeople,
  listVideos,
  optimizeVideoPlayback,
  removeVideoCategoryTag,
  removeVideoPerson,
  replaceVideoCover,
  startSubtitleService,
  stopSubtitleService,
  updateVideo,
  updateVideoCategoryTag,
  updateVideoPerson,
  uploadVideoPart
} from "../api";
import type { ConfirmDialogOptions } from "../components/ConfirmDialog";
import { formatError } from "../lib/formatError";
import { isCurrentRequest, nextRequestId } from "../lib/requestGeneration";
import type { PageKey } from "../lib/routing";
import { sortByPinyinName } from "../lib/sort";
import type {
  SubtitleJob,
  SubtitleServiceLogs,
  SubtitleServiceStatus,
  VideoCategoryTag,
  VideoDetail,
  VideoItem,
  VideoPlaybackDiagnostics,
  VideoPerson,
  VideoUploadSession
} from "../types";
import {
  delay,
  getFileExtension,
  isSupportedVideoFile,
  isVideoMetadataRepairPending,
  splitCommaList,
  supportedVideoFormatLabel,
  videoPartSize,
  videoPartUploadMaxAttempts,
  videoPartUploadRetryDelayMs,
  videoResumeStorageKey as legacyVideoResumeStorageKey,
  videoUploadQueueStorageKey
} from "../lib/utils";
import {
  loadStoredVideoUploadQueue,
  makeVideoQueueItem,
  saveStoredVideoUploadQueue,
  videoFileFingerprint,
  type VideoUploadQueueItem,
  type VideoUploadQueueStatus
} from "../lib/videoUploadQueue";

export const videoPageSize = 24;

type UseVideosOptions = {
  page: PageKey;
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  canAddVideos: boolean;
  canDeleteVideos: boolean;
  canEditVideos: boolean;
  onNavigate: (page: PageKey) => void;
};

export function useVideos({
  page,
  confirm,
  canAddVideos,
  canDeleteVideos,
  canEditVideos,
  onNavigate
}: UseVideosOptions) {
  const [videoItems, setVideoItems] = useState<VideoItem[]>([]);
  const [videoTotal, setVideoTotal] = useState(0);
  const [videoOffset, setVideoOffset] = useState(0);
  const [videoCategoryTags, setVideoCategoryTags] = useState<VideoCategoryTag[]>([]);
  const [videoPeople, setVideoPeople] = useState<VideoPerson[]>([]);
  const [selectedVideoCategoryIds, setSelectedVideoCategoryIds] = useState<number[]>([]);
  const [selectedVideoPersonIds, setSelectedVideoPersonIds] = useState<number[]>([]);
  const [videoTypeFilter, setVideoTypeFilter] = useState<"all" | "short" | "long">("all");
  const [videoSearch, setVideoSearch] = useState("");
  const [activeLightboxIndex, setActiveLightboxIndex] = useState<number | null>(null);
  const [selectedVideo, setSelectedVideo] = useState<VideoDetail | null>(null);
  const selectedVideoCodecRepairVideoId = useRef<number | null>(null);
  const selectedVideoCodecRepairPolls = useRef(0);
  const [videoPlayerUrl, setVideoPlayerUrl] = useState("");
  const [videoPlaybackDiagnostics, setVideoPlaybackDiagnostics] = useState<VideoPlaybackDiagnostics | null>(null);
  const [videoPlaybackDiagnosticsLoading, setVideoPlaybackDiagnosticsLoading] = useState(false);
  const [videoFiles, setVideoFiles] = useState<File[]>([]);
  const [videoTitle, setVideoTitle] = useState("");
  const [videoDescription, setVideoDescription] = useState("");
  const [videoUploadCategoryIds, setVideoUploadCategoryIds] = useState<number[]>([]);
  const [videoUploadPersonIds, setVideoUploadPersonIds] = useState<number[]>([]);
  const [videoUploadTypeMode, setVideoUploadTypeMode] = useState<"auto" | "short" | "long">("auto");
  const [videoUploadNewCategories, setVideoUploadNewCategories] = useState("");
  const [videoUploadGenerateSubtitles, setVideoUploadGenerateSubtitles] = useState(false);
  const [videoUploadProgress, setVideoUploadProgress] = useState(0);
  const [videoUploadSession, setVideoUploadSession] = useState<VideoUploadSession | null>(null);
  const [videoUploadCurrentIndex, setVideoUploadCurrentIndex] = useState(0);
  const [videoUploadTotalCount, setVideoUploadTotalCount] = useState(0);
  const [videoUploadBusy, setVideoUploadBusy] = useState(false);
  const [videoListRefreshing, setVideoListRefreshing] = useState(false);
  const [videoUploadQueue, setVideoUploadQueue] = useState<VideoUploadQueueItem[]>(() => loadStoredVideoUploadQueue());
  const videoUploadQueueRef = useRef<VideoUploadQueueItem[]>(videoUploadQueue);
  const [newVideoCategoryName, setNewVideoCategoryName] = useState("");
  const [newVideoPersonName, setNewVideoPersonName] = useState("");
  const [newVideoPersonNote, setNewVideoPersonNote] = useState("");
  const [newVideoPersonAvatar, setNewVideoPersonAvatar] = useState<File | null>(null);
  const [isVideoEditModalOpen, setIsVideoEditModalOpen] = useState(false);
  const [editVideoTitle, setEditVideoTitle] = useState("");
  const [editVideoDescription, setEditVideoDescription] = useState("");
  const [editVideoType, setEditVideoType] = useState<"short" | "long">("short");
  const [editVideoCategoryIds, setEditVideoCategoryIds] = useState<number[]>([]);
  const [editVideoPersonIds, setEditVideoPersonIds] = useState<number[]>([]);
  const [isCategoryManageModalOpen, setIsCategoryManageModalOpen] = useState(false);
  const [isVideoPersonManageModalOpen, setIsVideoPersonManageModalOpen] = useState(false);
  const [editingCategoryId, setEditingCategoryId] = useState<number | null>(null);
  const [editingCategoryName, setEditingCategoryName] = useState("");
  const [newManageCategoryName, setNewManageCategoryName] = useState("");
  const [editingPersonId, setEditingPersonId] = useState<number | null>(null);
  const [editingPersonName, setEditingPersonName] = useState("");
  const [editingPersonNote, setEditingPersonNote] = useState("");
  const [editingPersonAvatar, setEditingPersonAvatar] = useState<File | null>(null);
  const [newManagePersonName, setNewManagePersonName] = useState("");
  const [newManagePersonNote, setNewManagePersonNote] = useState("");
  const [newManagePersonAvatar, setNewManagePersonAvatar] = useState<File | null>(null);

  const filteredVideoCategoryTags = useMemo(() => sortByPinyinName(videoCategoryTags), [videoCategoryTags]);
  const filteredVideoPeople = useMemo(() => sortByPinyinName(videoPeople), [videoPeople]);
  const selectedVideoCategories = useMemo(
    () => videoCategoryTags.filter((tag) => selectedVideoCategoryIds.includes(tag.id)),
    [selectedVideoCategoryIds, videoCategoryTags]
  );
  const selectedVideoPeople = useMemo(
    () => videoPeople.filter((person) => selectedVideoPersonIds.includes(person.id)),
    [selectedVideoPersonIds, videoPeople]
  );
  const [subtitleServiceStatus, setSubtitleServiceStatus] = useState<SubtitleServiceStatus | null>(null);
  const [subtitleServiceLogs, setSubtitleServiceLogs] = useState<SubtitleServiceLogs | null>(null);
  const [subtitleJobs, setSubtitleJobs] = useState<SubtitleJob[]>([]);
  const [subtitleJobsLoaded, setSubtitleJobsLoaded] = useState(false);
  const [subtitleServiceBusy, setSubtitleServiceBusy] = useState(false);
  const [subtitleServiceNotice, setSubtitleServiceNotice] = useState<string | null>(null);
  const [subtitleLogsOpen, setSubtitleLogsOpen] = useState(false);

  const activeSubtitleJobs = useMemo(
    () => subtitleJobs.filter((job) => ["pending", "running"].includes(job.track.status)),
    [subtitleJobs]
  );
  const visibleSubtitleJobs = useMemo(() => subtitleJobs.slice(0, 8), [subtitleJobs]);
  const [error, setError] = useState<string | null>(null);
  const errorAutoDismissRef = useRef(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!error || !errorAutoDismissRef.current) return;
    errorAutoDismissRef.current = false;
    const timer = window.setTimeout(() => setError(null), 15000);
    return () => window.clearTimeout(timer);
  }, [error]);
  const [isVideoUploadModalOpen, setIsVideoUploadModalOpen] = useState(false);
  const [editingVideoId, setEditingVideoId] = useState<number | null>(null);
  const [editVideoOriginalCategoryIds, setEditVideoOriginalCategoryIds] = useState<number[]>([]);
  const [editVideoOriginalPersonIds, setEditVideoOriginalPersonIds] = useState<number[]>([]);
  const previousPageRef = useRef<PageKey>(page);
  const videoRequestIdRef = useRef(0);
  const videoTotalPages = Math.max(1, Math.ceil(videoTotal / videoPageSize));
  const videoCurrentPage = Math.floor(videoOffset / videoPageSize) + 1;
  const selectedVideoSubtitlePollingKey =
    selectedVideo?.subtitle_tracks.map((track) => `${track.id}:${track.status}`).join("|") ?? "";
  const activeSubtitleJobCount = activeSubtitleJobs.length;
  async function refreshVideoTaxonomy() {
    const [categories, people] = await Promise.all([listVideoCategoryTags(), listVideoPeople()]);
    setVideoCategoryTags(sortByPinyinName(categories));
    setVideoPeople(sortByPinyinName(people));
  }

  async function refreshVideos(
    nextOffset = videoOffset,
    categoryIds = selectedVideoCategoryIds,
    personIds = selectedVideoPersonIds,
    query = videoSearch,
    typeFilter = videoTypeFilter,
  ) {
    const requestId = nextRequestId(videoRequestIdRef);
    const response = await listVideos(categoryIds, personIds, query, nextOffset, videoPageSize, typeFilter === "all" ? null : typeFilter);
    if (!isCurrentRequest(videoRequestIdRef, requestId)) {
      return;
    }
    setVideoItems(response.items);
    setVideoTotal(response.total);
    setVideoOffset(response.offset);
    setSelectedVideo((current) => {
      if (!current) {
        return current;
      }
      const listed = response.items.find((item) => item.id === current.id);
      return listed ? { ...current, ...listed } : current;
    });
  }

  async function refreshSubtitleJobs() {
    const jobs = await listSubtitleJobs();
    setSubtitleJobs(jobs);
    setSubtitleJobsLoaded(true);
  }

  async function refreshSubtitleServicePanel() {
    const operations: Promise<unknown>[] = [
      getSubtitleServiceStatus().then((status) => setSubtitleServiceStatus(status)),
      refreshSubtitleJobs()
    ];
    if (subtitleLogsOpen) {
      operations.push(getSubtitleServiceLogs(200).then((logs) => setSubtitleServiceLogs(logs)));
    }
    const results = await Promise.allSettled(operations);
    const failed = results.find((result) => result.status === "rejected");
    if (failed?.status === "rejected") {
      throw failed.reason instanceof Error ? failed.reason : new Error("字幕服务状态刷新失败。");
    }
  }

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshVideoTaxonomy(), refreshVideos(0, [], [], "", "all")]);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "视频数据初始化失败。");
      }
    })();
  }, []);

  useEffect(() => {
    videoUploadQueueRef.current = videoUploadQueue;
    saveStoredVideoUploadQueue(videoUploadQueue);
  }, [videoUploadQueue]);

  useEffect(() => {
    if (!videoUploadBusy || !videoUploadQueue.some((item) => item.status === "uploading")) {
      return undefined;
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [videoUploadBusy, videoUploadQueue]);

  useEffect(() => {
    let canceled = false;
    const reconcile = async () => {
      const candidates = videoUploadQueueRef.current.filter((item) => item.progress >= 100 || item.status === "finalizing");
      if (candidates.length === 0) return;
      const ids = await Promise.all(candidates.map(async (item) => {
        try {
          const response = await listVideos([], [], item.filename, 0, 100);
          return response.items.some((video) => video.filename === item.filename) ? item.id : null;
        } catch {
          return null;
        }
      }));
      if (canceled) return;
      const completedIds = new Set(ids.filter((id): id is string => Boolean(id)));
      if (completedIds.size > 0) {
        setVideoUploadQueueSynced((current) => current.filter((item) => !completedIds.has(item.id)));
      }
    };
    void reconcile();
    return () => { canceled = true; };
  }, []);

  useEffect(() => {
    if (page === "videos" && previousPageRef.current !== "videos") {
      void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter);
    }
    previousPageRef.current = page;
  }, [page]);

  useEffect(() => {
    if (page !== "videos") {
      return undefined;
    }
    let canceled = false;
    const shouldKeepPolling = activeSubtitleJobCount > 0 || subtitleLogsOpen;
    const refresh = async () => {
      await Promise.allSettled([
        listSubtitleJobs()
          .then((jobs) => {
            if (!canceled) {
              setSubtitleJobs(jobs);
              setSubtitleJobsLoaded(true);
            }
          })
          .catch((cause) => {
            if (!canceled) {
              setError(cause instanceof Error ? cause.message : "字幕任务刷新失败。");
            }
          }),
        getSubtitleServiceStatus()
          .then((status) => {
            if (!canceled) {
              setSubtitleServiceStatus(status);
            }
          })
          .catch((cause) => {
            if (!canceled) {
              setSubtitleServiceNotice(`状态刷新失败：${cause instanceof Error ? cause.message : "字幕服务状态刷新失败。"}`);
            }
          }),
        subtitleLogsOpen
          ? getSubtitleServiceLogs(200)
              .then((logs) => {
                if (!canceled) {
                  setSubtitleServiceLogs(logs);
                }
              })
              .catch((cause) => {
                if (!canceled) {
                  setError(cause instanceof Error ? cause.message : "字幕日志刷新失败。");
                }
              })
          : Promise.resolve()
      ]);
    };
    void refresh();
    if (!shouldKeepPolling) {
      return () => {
        canceled = true;
      };
    }
    const timer = window.setInterval(refresh, 4000);
    return () => {
      canceled = true;
      window.clearInterval(timer);
    };
  }, [page, subtitleLogsOpen, activeSubtitleJobCount]);

  useEffect(() => {
    const hasPendingSubtitle = selectedVideo?.subtitle_tracks.some((track) => ["pending", "running"].includes(track.status));
    if (!selectedVideo || (!["uploaded", "processing"].includes(selectedVideo.status) && !hasPendingSubtitle)) {
      return undefined;
    }
    const videoId = selectedVideo.id;
    const timer = window.setInterval(async () => {
      try {
        const detail = await getVideo(videoId);
        setSelectedVideo(detail);
        setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "视频状态刷新失败。");
      }
    }, 3000);
    return () => window.clearInterval(timer);
  }, [selectedVideo?.id, selectedVideo?.status, selectedVideoSubtitlePollingKey]);

  useEffect(() => {
    if (!selectedVideo) {
      selectedVideoCodecRepairVideoId.current = null;
      selectedVideoCodecRepairPolls.current = 0;
      return undefined;
    }
    if (selectedVideoCodecRepairVideoId.current !== selectedVideo.id) {
      selectedVideoCodecRepairVideoId.current = selectedVideo.id;
      selectedVideoCodecRepairPolls.current = 0;
    }
    if (!isVideoMetadataRepairPending(selectedVideo) || selectedVideoCodecRepairPolls.current >= 5) {
      return undefined;
    }
    const videoId = selectedVideo.id;
    const timer = window.setTimeout(async () => {
      selectedVideoCodecRepairPolls.current += 1;
      try {
        const detail = await getVideo(videoId);
        setSelectedVideo(detail);
        setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "视频编码信息刷新失败。");
      }
    }, 3000);
    return () => window.clearTimeout(timer);
  }, [
    selectedVideo?.id,
    selectedVideo?.status,
    selectedVideo?.original_video_codec,
    selectedVideo?.video_codec,
    selectedVideo?.processing_error
  ]);

  useEffect(() => {
    if (!selectedVideo) {
      setVideoPlayerUrl("");
      return;
    }
    setVideoPlayerUrl(selectedVideo.play_url || selectedVideo.stream_url);
  }, [selectedVideo?.id, selectedVideo?.play_url, selectedVideo?.stream_url]);

  useEffect(() => {
    setVideoPlaybackDiagnostics(null);
  }, [selectedVideo?.id]);
  function setVideoUploadQueueSynced(updater: (current: VideoUploadQueueItem[]) => VideoUploadQueueItem[]) {
    setVideoUploadQueue((current) => {
      const next = updater(current);
      videoUploadQueueRef.current = next;
      saveStoredVideoUploadQueue(next);
      return next;
    });
  }

  function updateVideoQueueItem(
    itemId: string,
    updater: Partial<VideoUploadQueueItem> | ((item: VideoUploadQueueItem) => VideoUploadQueueItem)
  ) {
    setVideoUploadQueueSynced((current) =>
      current.map((item) => {
        if (item.id !== itemId) {
          return item;
        }
        return typeof updater === "function" ? updater(item) : { ...item, ...updater };
      })
    );
  }

  function getVideoUploadOptionsForFile(file: File, totalCount: number) {
    return {
      title: totalCount === 1 ? videoTitle.trim() || file.name.replace(/\.[^.]+$/, "") : file.name.replace(/\.[^.]+$/, ""),
      description: videoDescription.trim(),
      categoryTagIds: videoUploadCategoryIds,
      categoryTagNames: splitCommaList(videoUploadNewCategories),
      personIds: videoUploadPersonIds,
      generateZhSubtitles: videoUploadGenerateSubtitles,
      videoType: videoUploadTypeMode === "auto" ? null : videoUploadTypeMode
    };
  }

  function handlePickVideoFile(files: FileList | null) {
    const picked = Array.from(files ?? []);
    const supportedPicked = picked.filter((file) => isSupportedVideoFile(file.name));
    setVideoFiles(supportedPicked);
    if (supportedPicked.length === 1 && !videoTitle.trim()) {
      setVideoTitle(supportedPicked[0].name.replace(/\.[^.]+$/, ""));
    } else if (supportedPicked.length > 1) {
      setVideoTitle("");
    }
    if (picked.length !== supportedPicked.length) {
      setError(`已忽略不支持的视频格式，仅支持 ${supportedVideoFormatLabel}。`);
    } else {
      setError(null);
    }
    const pickedIds = new Set(supportedPicked.map((file) => videoFileFingerprint(file)));
    const pickedById = new Map(supportedPicked.map((file) => [videoFileFingerprint(file), file]));
    setVideoUploadQueueSynced((current) => {
      const existingIds = new Set(current.map((item) => item.id));
      const next = current.map((item) => {
        if (!pickedIds.has(item.id) || item.status === "completed") {
          return item;
        }
        const file = pickedById.get(item.id);
        return {
          ...item,
          filename: file?.name ?? item.filename,
          size: file?.size ?? item.size,
          lastModified: file?.lastModified ?? item.lastModified,
          contentType: file?.type || item.contentType,
          status: "queued" as VideoUploadQueueStatus,
          error: null
        };
      });
      for (const file of supportedPicked) {
        const id = videoFileFingerprint(file);
        if (!existingIds.has(id)) {
          next.push(makeVideoQueueItem(file, getVideoUploadOptionsForFile(file, supportedPicked.length)));
        }
      }
      return next;
    });
    setVideoUploadProgress(0);
    setVideoUploadSession(null);
  }

  function handleToggleVideoFilterCategory(tagId: number) {
    const next = selectedVideoCategoryIds.includes(tagId)
      ? selectedVideoCategoryIds.filter((id) => id !== tagId)
      : [...selectedVideoCategoryIds, tagId];
    setSelectedVideoCategoryIds(next);
    void refreshVideos(0, next, selectedVideoPersonIds, videoSearch, videoTypeFilter);
  }

  function handleToggleVideoFilterPerson(personId: number) {
    const next = selectedVideoPersonIds.includes(personId)
      ? selectedVideoPersonIds.filter((id) => id !== personId)
      : [...selectedVideoPersonIds, personId];
    setSelectedVideoPersonIds(next);
    void refreshVideos(0, selectedVideoCategoryIds, next, videoSearch, videoTypeFilter);
  }

  function handleToggleVideoUploadCategory(tagId: number) {
    setVideoUploadCategoryIds((current) =>
      current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]
    );
  }

  function handleToggleVideoUploadPerson(personId: number) {
    setVideoUploadPersonIds((current) =>
      current.includes(personId) ? current.filter((id) => id !== personId) : [...current, personId]
    );
  }

  async function handleCreateVideoCategory() {
    if (!newVideoCategoryName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const tag = await createVideoCategoryTag(newVideoCategoryName.trim());
      setNewVideoCategoryName("");
      await refreshVideoTaxonomy();
      setVideoUploadCategoryIds((current) => Array.from(new Set([...current, tag.id])));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建视频类别标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateVideoPerson() {
    if (!newVideoPersonName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const person = await createVideoPerson(newVideoPersonName.trim(), newVideoPersonNote.trim(), newVideoPersonAvatar);
      setNewVideoPersonName("");
      setNewVideoPersonNote("");
      setNewVideoPersonAvatar(null);
      await refreshVideoTaxonomy();
      setVideoUploadPersonIds((current) => Array.from(new Set([...current, person.id])));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建视频人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function openVideo(videoId: number) {
    setError(null);
    try {
      setSelectedVideo(await getVideo(videoId));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载视频详情失败。");
    }
  }


  async function handleDeleteVideoItem(video: { id: number; title: string }): Promise<boolean> {
    if (!await confirm({
      title: "删除视频",
      message: `确认删除视频「${video.title}」吗？删除后文件将被永久移除且不可恢复。`,
      confirmLabel: "删除",
      tone: "danger"
    })) {
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteVideo(video.id);
      if (selectedVideo?.id === video.id) {
        setSelectedVideo(null);
        setVideoPlayerUrl("");
      }
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除视频失败。");
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCurrentVideo(): Promise<boolean> {
    if (!selectedVideo) {
      return false;
    }
    return handleDeleteVideoItem(selectedVideo);
  }

  async function handleReplaceVideoCover(files: FileList | null) {
    if (!selectedVideo || !files?.[0]) {
      return;
    }
    const file = files[0];
    setBusy(true);
    setError(null);
    try {
      const detail = await replaceVideoCover(selectedVideo.id, file);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "替换视频封面失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleLoadVideoPlaybackDiagnostics() {
    if (!selectedVideo) {
      return;
    }
    setVideoPlaybackDiagnosticsLoading(true);
    setError(null);
    try {
      setVideoPlaybackDiagnostics(await getVideoPlaybackDiagnostics(selectedVideo.id));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取播放诊断失败。");
    } finally {
      setVideoPlaybackDiagnosticsLoading(false);
    }
  }

  async function handleOptimizeSelectedVideoPlayback() {
    if (!selectedVideo) {
      return;
    }
    if (!await confirm({ title: "优化视频播放", message: "会覆盖当前 MinIO 中的视频对象，并重新编码为更适合拖动进度条的 MP4。继续吗？", confirmLabel: "开始优化" })) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await optimizeVideoPlayback(selectedVideo.id);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      setVideoPlaybackDiagnostics(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "启动播放优化失败。");
    } finally {
      setBusy(false);
    }
  }

  function openVideoEditModal(target?: VideoItem | VideoDetail | null) {
    const vid = target ?? selectedVideo;
    if (!vid) return;
    setEditingVideoId(vid.id);
    setEditVideoTitle(vid.title);
    setEditVideoDescription(vid.description || "");
    setEditVideoType(vid.video_type || "short");
    setEditVideoCategoryIds(vid.category_tags.map(t => t.id));
    setEditVideoPersonIds(vid.people.map(p => p.id));
    setEditVideoOriginalCategoryIds(vid.category_tags.map((tag) => tag.id));
    setEditVideoOriginalPersonIds(vid.people.map((person) => person.id));
    setIsVideoEditModalOpen(true);
  }

  async function handleSaveVideoEdit() {
    if (editingVideoId == null) return;
    const videoId = editingVideoId;
    setBusy(true);
    setError(null);
    try {
      await updateVideo(videoId, {
        title: editVideoTitle.trim() || "未命名视频",
        description: editVideoDescription.trim() || null,
        video_type: editVideoType
      });
      const oldCategoryIds = new Set(editVideoOriginalCategoryIds);
      const newCategoryIds = new Set(editVideoCategoryIds);
      for (const tagId of editVideoCategoryIds) {
        if (!oldCategoryIds.has(tagId)) {
          await addVideoCategoryTag(videoId, { tagId });
        }
      }
      for (const tagId of editVideoOriginalCategoryIds) {
        if (!newCategoryIds.has(tagId)) {
          await removeVideoCategoryTag(videoId, tagId);
        }
      }
      const oldPersonIds = new Set(editVideoOriginalPersonIds);
      const newPersonIds = new Set(editVideoPersonIds);
      for (const personId of editVideoPersonIds) {
        if (!oldPersonIds.has(personId)) {
          await addVideoPerson(videoId, personId);
        }
      }
      for (const personId of editVideoOriginalPersonIds) {
        if (!newPersonIds.has(personId)) {
          await removeVideoPerson(videoId, personId);
        }
      }
      const detail = await getVideo(videoId);
      if (selectedVideo?.id === videoId) {
        setSelectedVideo(detail);
      }
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      setIsVideoEditModalOpen(false);
      setEditingVideoId(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存视频信息失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateManageCategory() {
    if (!newManageCategoryName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createVideoCategoryTag(newManageCategoryName.trim());
      setNewManageCategoryName("");
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建分区失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateManageCategory(tagId: number) {
    if (!editingCategoryName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateVideoCategoryTag(tagId, editingCategoryName.trim());
      setEditingCategoryId(null);
      setEditingCategoryName("");
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新分区失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteManageCategory(tagId: number) {
    if (!await confirm({ title: "删除分区", message: "确认删除此分区吗？", confirmLabel: "删除", tone: "danger" })) return;
    setBusy(true);
    setError(null);
    try {
      await deleteVideoCategoryTag(tagId);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除分区失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateManagePerson() {
    if (!newManagePersonName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createVideoPerson(newManagePersonName.trim(), newManagePersonNote.trim(), newManagePersonAvatar);
      setNewManagePersonName("");
      setNewManagePersonNote("");
      setNewManagePersonAvatar(null);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建UP主失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUpdateManagePerson(personId: number) {
    if (!editingPersonName.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await updateVideoPerson(personId, editingPersonName.trim(), editingPersonNote.trim() || null, editingPersonAvatar);
      setEditingPersonId(null);
      setEditingPersonName("");
      setEditingPersonNote("");
      setEditingPersonAvatar(null);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "更新UP主失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteManagePerson(personId: number) {
    if (!await confirm({ title: "删除UP主", message: "确认删除此UP主吗？", confirmLabel: "删除", tone: "danger" })) return;
    setBusy(true);
    setError(null);
    try {
      await deleteVideoPerson(personId);
      await refreshVideoTaxonomy();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除UP主失败。");
    } finally {
      setBusy(false);
    }
  }

  async function resolveVideoUploadSession(file: File, item: VideoUploadQueueItem): Promise<VideoUploadSession> {
    if (item.sessionId) {
      try {
        const existing = await getVideoUploadSession(item.sessionId);
        setVideoUploadSession(existing);
        updateVideoQueueItem(item.id, {
          partSize: existing.part_size,
          totalParts: existing.total_parts,
          uploadedParts: existing.uploaded_parts,
          progress: Math.round((existing.uploaded_parts.length / existing.total_parts) * 100)
        });
        return existing;
      } catch {
        updateVideoQueueItem(item.id, { sessionId: null, uploadedParts: [], progress: 0 });
      }
    }
    const session = await createVideoUploadSession({
      title: item.title.trim(),
      description: item.description.trim() || null,
      filename: file.name,
      content_type: file.type || item.contentType,
      size_bytes: file.size,
      part_size: item.partSize || videoPartSize
    });
    setVideoUploadSession(session);
    updateVideoQueueItem(item.id, {
      sessionId: session.id,
      partSize: session.part_size,
      totalParts: session.total_parts,
      uploadedParts: session.uploaded_parts,
      progress: Math.round((session.uploaded_parts.length / session.total_parts) * 100)
    });
    return session;
  }

  async function uploadVideoPartWithRetry(sessionId: string, partIndex: number, blob: Blob, filename: string): Promise<void> {
    let lastCause: unknown = null;
    for (let attempt = 1; attempt <= videoPartUploadMaxAttempts; attempt += 1) {
      try {
        await uploadVideoPart(sessionId, partIndex, blob, filename);
        return;
      } catch (cause) {
        lastCause = cause;
        if (attempt >= videoPartUploadMaxAttempts) {
          break;
        }
        await delay(videoPartUploadRetryDelayMs * attempt);
      }
    }
    throw lastCause instanceof Error ? lastCause : new Error("分片上传失败");
  }

  async function handleConfirmVideoUpload() {
    const selectedFilesById = new Map(videoFiles.map((file) => [videoFileFingerprint(file), file]));
    let preparedQueue = videoUploadQueueRef.current;
    if (videoFiles.length > 0) {
      const existingIds = new Set(preparedQueue.map((item) => item.id));
      preparedQueue = preparedQueue.map((item) => {
        const file = selectedFilesById.get(item.id);
        if (!file || item.status === "completed") {
          return item;
        }
        return {
          ...item,
          ...getVideoUploadOptionsForFile(file, videoFiles.length),
          filename: file.name,
          size: file.size,
          lastModified: file.lastModified,
          contentType: file.type || item.contentType,
          status: "queued" as VideoUploadQueueStatus,
          error: null
        };
      });
      const addedItems: VideoUploadQueueItem[] = [];
      for (const file of videoFiles) {
        const id = videoFileFingerprint(file);
        if (!existingIds.has(id)) {
          addedItems.push(makeVideoQueueItem(file, getVideoUploadOptionsForFile(file, videoFiles.length)));
        }
      }
      preparedQueue = [...preparedQueue, ...addedItems];
      setVideoUploadQueueSynced(() => preparedQueue);
    }
    const filesToUpload = preparedQueue
      .filter((item) => item.status !== "completed" && selectedFilesById.has(item.id))
      .map((item) => ({ item, file: selectedFilesById.get(item.id)! }));
    let workingQueue = preparedQueue;
    const syncWorkingQueueItem = (
      itemId: string,
      updater: Partial<VideoUploadQueueItem> | ((item: VideoUploadQueueItem) => VideoUploadQueueItem)
    ) => {
      workingQueue = workingQueue.map((queueItem) => {
        if (queueItem.id !== itemId) {
          return queueItem;
        }
        return typeof updater === "function" ? updater(queueItem) : { ...queueItem, ...updater };
      });
      setVideoUploadQueueSynced(() => workingQueue);
    };
    const totalCount = filesToUpload.length;
    if (totalCount === 0) {
      const hasInterrupted = preparedQueue.some((item) => item.status === "needs_file" || item.status === "failed");
      if (hasInterrupted) {
        setError("请重新选择队列里标记为“需重选文件”的原视频文件后继续上传。");
      }
      return;
    }
    if (videoFiles.length === 1 && !videoTitle.trim()) {
      return;
    }
    setVideoUploadBusy(true);
    setError(null);
    setVideoUploadTotalCount(totalCount);

    let completedCount = 0;
    let lastError: string | null = null;

    for (let fileIndex = 0; fileIndex < totalCount; fileIndex += 1) {
      const { item, file } = filesToUpload[fileIndex];
      if (!isSupportedVideoFile(file.name)) {
        lastError = `"${file.name}" 不是支持的视频格式（${supportedVideoFormatLabel}），已跳过。`;
        syncWorkingQueueItem(item.id, { status: "failed", error: lastError });
        continue;
      }

      try {
        flushSync(() => {
          setVideoUploadCurrentIndex(fileIndex);
          setVideoUploadProgress(0);
          setVideoUploadSession(null);
        });

        syncWorkingQueueItem(item.id, { status: "uploading", error: null });
        let session = await resolveVideoUploadSession(file, item);
        const uploaded = new Set(session.uploaded_parts);
        setVideoUploadSession(session);
        syncWorkingQueueItem(item.id, {
          sessionId: session.id,
          partSize: session.part_size,
          totalParts: session.total_parts,
          uploadedParts: Array.from(uploaded).sort((left, right) => left - right),
          progress: Math.round((uploaded.size / session.total_parts) * 100)
        });
        for (let index = 0; index < session.total_parts; index += 1) {
          if (uploaded.has(index)) {
            const progress = Math.round((uploaded.size / session.total_parts) * 100);
            setVideoUploadProgress(progress);
            syncWorkingQueueItem(item.id, { progress });
            continue;
          }
          const start = index * session.part_size;
          const end = Math.min(start + session.part_size, file.size);
          await uploadVideoPartWithRetry(session.id, index, file.slice(start, end), file.name);
          uploaded.add(index);
          const uploadedParts = Array.from(uploaded).sort((left, right) => left - right);
          session = { ...session, uploaded_parts: uploadedParts };
          setVideoUploadSession(session);
          const progress = Math.round((uploadedParts.length / session.total_parts) * 100);
          setVideoUploadProgress(progress);
          syncWorkingQueueItem(item.id, { uploadedParts, progress });
        }
        syncWorkingQueueItem(item.id, { status: "finalizing", error: null, progress: 100 });
        session = await getVideoUploadSession(session.id);
        setVideoUploadSession(session);
        const detail = await completeVideoUpload(session.id, {
          category_tag_ids: item.categoryTagIds,
          category_tag_names: item.categoryTagNames,
          person_ids: item.personIds,
          generate_zh_subtitles: item.generateZhSubtitles,
          video_type: item.videoType
        });
        syncWorkingQueueItem(item.id, {
          sessionId: null,
          uploadedParts: session.uploaded_parts,
          progress: 100,
          status: "completed",
          error: null,
          completedVideoId: detail.id
        });
        completedCount += 1;
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : "视频上传失败。";
        let recovered = false;
        try {
          const response = await listVideos([], [], file.name, 0, 100);
          recovered = response.items.some((video) => video.filename === file.name);
        } catch {
          recovered = false;
        }
        if (recovered) {
          syncWorkingQueueItem(item.id, { sessionId: null, progress: 100, status: "completed", error: null });
          completedCount += 1;
        } else {
          lastError = `"${file.name}" ${message}`;
          syncWorkingQueueItem(item.id, { status: "failed", error: message });
        }
        console.error(`[批量上传] 第 ${fileIndex + 1}/${totalCount} 个失败: ${file.name}`, cause);
      }
    }

    if (completedCount > 0) {
      setVideoFiles([]);
      setVideoTitle("");
      setVideoDescription("");
      setVideoUploadCategoryIds([]);
      setVideoUploadPersonIds([]);
      setVideoUploadNewCategories("");
      setVideoUploadTypeMode("auto");
      void refreshVideoTaxonomy();
      void refreshVideos(0, [], [], "", "all");
      if (videoUploadGenerateSubtitles) {
        void refreshSubtitleServicePanel().catch((cause) => {
          setSubtitleServiceNotice(`状态刷新失败：${cause instanceof Error ? cause.message : "字幕服务状态刷新失败。"}`);
        });
      }
    }

    setVideoUploadSession(null);
    setVideoUploadProgress(0);
    setVideoUploadCurrentIndex(0);
    setVideoUploadTotalCount(0);

    const remainingQueue = workingQueue.filter((item) => item.status !== "completed");
    if (lastError) {
      errorAutoDismissRef.current = true;
      setError(`${lastError}（已完成 ${completedCount}/${totalCount} 个）`);
    } else if (remainingQueue.length > 0) {
      setError("还有未完成的视频，请重新选择对应原文件后继续上传。");
    } else {
      setVideoUploadQueueSynced(() => []);
      setIsVideoUploadModalOpen(false);
    }
    setVideoUploadBusy(false);
  }

  async function handleCancelVideoUpload() {
    const sessionsToCancel = videoUploadQueueRef.current
      .filter((item) => item.sessionId && item.status !== "completed")
      .map((item) => item.sessionId!);
    if (sessionsToCancel.length === 0 && !videoUploadSession) {
      window.localStorage.removeItem(legacyVideoResumeStorageKey);
      window.localStorage.removeItem(videoUploadQueueStorageKey);
      setVideoUploadProgress(0);
      setVideoUploadQueueSynced(() => []);
      setVideoFiles([]);
      return;
    }
    if (!await confirm({ title: "清理上传队列", message: "确认清理当前视频上传队列和未完成的续传会话吗？", confirmLabel: "清理", tone: "danger" })) {
      return;
    }
    setVideoUploadBusy(true);
    setError(null);
    try {
      await Promise.allSettled(sessionsToCancel.map((sessionId) => cancelVideoUpload(sessionId)));
      if (videoUploadSession && !sessionsToCancel.includes(videoUploadSession.id)) {
        await cancelVideoUpload(videoUploadSession.id);
      }
      window.localStorage.removeItem(legacyVideoResumeStorageKey);
      window.localStorage.removeItem(videoUploadQueueStorageKey);
      setVideoUploadSession(null);
      setVideoUploadProgress(0);
      setVideoUploadCurrentIndex(0);
      setVideoUploadTotalCount(0);
      setVideoUploadQueueSynced(() => []);
      setVideoFiles([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消视频上传失败。");
    } finally {
      setVideoUploadBusy(false);
    }
  }

  async function handleGenerateSelectedVideoSubtitles() {
    if (!selectedVideo) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await generateVideoSubtitles(selectedVideo.id);
      const detail = await getVideo(selectedVideo.id);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      await refreshSubtitleJobs();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "提交字幕生成失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleStartSubtitleService() {
    setSubtitleServiceBusy(true);
    setError(null);
    setSubtitleServiceNotice(null);
    try {
      setSubtitleServiceStatus(await startSubtitleService());
      setSubtitleServiceLogs(await getSubtitleServiceLogs(200));
      await refreshSubtitleServicePanel();
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "启动翻译服务失败。";
      setError(message);
      setSubtitleServiceNotice(`启动失败：${message}`);
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleStopSubtitleService() {
    const message =
      activeSubtitleJobs.length > 0
        ? `当前有 ${activeSubtitleJobs.length} 个字幕任务正在执行。关闭翻译服务会取消这些任务，确定继续吗？`
        : "确定关闭翻译服务吗？";
    if (!await confirm({ title: "关闭翻译服务", message, confirmLabel: "关闭服务", tone: "danger" })) {
      return;
    }
    setSubtitleServiceBusy(true);
    setError(null);
    setSubtitleServiceNotice(null);
    try {
      setSubtitleServiceStatus(await stopSubtitleService(true));
      await refreshSubtitleServicePanel();
      setSubtitleServiceNotice("翻译服务已关闭");
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter);
      if (selectedVideo) {
        const detail = await getVideo(selectedVideo.id);
        setSelectedVideo(detail);
      }
    } catch (cause) {
      const errorMessage = cause instanceof Error ? cause.message : "关闭翻译服务失败。";
      setError(errorMessage);
      setSubtitleServiceNotice(`关闭失败：${errorMessage}`);
      try {
        await refreshSubtitleServicePanel();
      } catch {
        // Keep the actionable shutdown error visible if the status refresh also fails.
      }
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleToggleSubtitleLogs() {
    const nextOpen = !subtitleLogsOpen;
    setSubtitleLogsOpen(nextOpen);
    if (!nextOpen) {
      return;
    }
    setSubtitleServiceBusy(true);
    setError(null);
    try {
      setSubtitleServiceLogs(await getSubtitleServiceLogs(200));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "读取翻译服务日志失败。");
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleCancelSubtitleJob(job: SubtitleJob) {
    if (!await confirm({ title: "取消字幕生成", message: `确定取消《${job.video_title}》的中文字幕生成吗？`, confirmLabel: "取消任务", tone: "danger" })) {
      return;
    }
    setSubtitleServiceBusy(true);
    setError(null);
    try {
      await cancelVideoSubtitles(job.video_id, job.track.id);
      await refreshSubtitleServicePanel();
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter);
      if (selectedVideo?.id === job.video_id) {
        setSelectedVideo(await getVideo(job.video_id));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消字幕任务失败。");
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function refreshVideoList() {
    setVideoListRefreshing(true);
    try {
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch, videoTypeFilter);
    } catch (cause) {
      setError(formatError(cause, "视频列表刷新失败。"));
    } finally {
      setVideoListRefreshing(false);
    }
  }

  return {
    error, setError, busy, canAddVideos, canDeleteVideos, canEditVideos,
    videoItems, videoTotal, videoOffset, videoPageSize, videoCategoryTags, videoPeople, selectedVideoCategoryIds,
    selectedVideoPersonIds, videoTypeFilter, videoSearch, activeLightboxIndex, selectedVideo, videoPlayerUrl,
    videoPlaybackDiagnostics, videoPlaybackDiagnosticsLoading, videoFiles, videoTitle, videoDescription,
    videoUploadCategoryIds, videoUploadPersonIds, videoUploadTypeMode, videoUploadNewCategories,
    videoUploadGenerateSubtitles, videoUploadProgress, videoUploadSession, videoUploadCurrentIndex,
    videoUploadTotalCount, videoUploadBusy, videoUploadQueue, videoListRefreshing,
    newVideoCategoryName, newVideoPersonName, newVideoPersonNote, newVideoPersonAvatar,
    isVideoEditModalOpen, editVideoTitle, editVideoDescription, editVideoType, editVideoCategoryIds, editVideoPersonIds,
    isCategoryManageModalOpen, isVideoPersonManageModalOpen, editingCategoryId, editingCategoryName,
    newManageCategoryName, editingPersonId, editingPersonName, editingPersonNote, editingPersonAvatar,
    newManagePersonName, newManagePersonNote, newManagePersonAvatar,
    filteredVideoCategoryTags, filteredVideoPeople, selectedVideoCategories, selectedVideoPeople,
    videoTotalPages, videoCurrentPage, editingVideoId, setEditingVideoId, isVideoUploadModalOpen,
    subtitleServiceStatus, subtitleServiceLogs, subtitleJobs, subtitleJobsLoaded, subtitleServiceBusy,
    subtitleServiceNotice, subtitleLogsOpen, activeSubtitleJobs, visibleSubtitleJobs,
    setVideoSearch, setVideoTypeFilter, setSelectedVideoCategoryIds, setSelectedVideoPersonIds,
    setActiveLightboxIndex, setVideoTitle, setVideoDescription, setVideoUploadCategoryIds, setVideoUploadPersonIds,
    setVideoUploadTypeMode, setVideoUploadNewCategories, setVideoUploadGenerateSubtitles,
    setNewVideoCategoryName, setNewVideoPersonName, setNewVideoPersonNote, setNewVideoPersonAvatar,
    setIsVideoUploadModalOpen, setIsVideoEditModalOpen, setEditVideoTitle, setEditVideoDescription, setEditVideoType,
    setEditVideoCategoryIds, setEditVideoPersonIds, setIsCategoryManageModalOpen, setIsVideoPersonManageModalOpen,
    setEditingCategoryId, setEditingCategoryName, setNewManageCategoryName, setEditingPersonId, setEditingPersonName,
    setEditingPersonNote, setEditingPersonAvatar, setNewManagePersonName, setNewManagePersonNote, setNewManagePersonAvatar,
    refreshVideos, refreshVideoList, handleToggleVideoFilterCategory, handleToggleVideoFilterPerson,
    handleToggleVideoUploadCategory, handleToggleVideoUploadPerson,
    handleCreateVideoCategory, handleCreateVideoPerson, openVideo, handleDeleteVideoItem, handleDeleteCurrentVideo,
    handleReplaceVideoCover, handleLoadVideoPlaybackDiagnostics, handleOptimizeSelectedVideoPlayback,
    openVideoEditModal, handleSaveVideoEdit,
    handleCreateManageCategory, handleUpdateManageCategory, handleDeleteManageCategory,
    handleCreateManagePerson, handleUpdateManagePerson, handleDeleteManagePerson,
    handlePickVideoFile, handleConfirmVideoUpload, handleCancelVideoUpload,
    handleGenerateSelectedVideoSubtitles, handleStartSubtitleService, handleStopSubtitleService,
    handleToggleSubtitleLogs, handleCancelSubtitleJob,
    setVideoListRefreshing, onNavigate
  };
}

export type VideosModel = ReturnType<typeof useVideos>;
