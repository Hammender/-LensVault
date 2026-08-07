import { useEffect, useMemo, useRef, useState } from "react";
import { flushSync } from "react-dom";
import {
  BarChart3,
  ArrowUp,
  Clapperboard,
  Download,
  Edit3,
  FileUp,
  FolderSync,
  GalleryHorizontalEnd,
  HomeIcon,
  ImagePlus,
  Info,
  LogOut,
  RotateCcw,
  Search,
  ScanSearch,
  Settings,
  SlidersHorizontal,
  Trash2,
  UploadCloud,
  UserPlus,
  UsersRound,
  X
} from "lucide-react";

import Home from "./Home";
import WorkspacePanel from "./components/WorkspacePanel";
import { useGalleryController } from "./controllers/useGalleryController";
import { usePeopleController } from "./controllers/usePeopleController";
import { useSubtitleController } from "./controllers/useSubtitleController";
import { useUploadController, type PendingGalleryUpload } from "./controllers/useUploadController";
import { useVideoController } from "./controllers/useVideoController";
import PhotoLightbox from "./PhotoLightbox";
import SearchableSelect from "./SearchableSelect";
import Statistics from "./Statistics";
import SimilarityReview from "./SimilarityReview";
import AcquisitionCenter from "./AcquisitionCenter";
import BiliVideoPlayer from "./BiliVideoPlayer";
import { useConfirm } from "./ConfirmDialog";
import { availablePhotoPersons, filterPersonMatches, resolveExistingPerson } from "./personPicker";
import { routeFromHash, setRoute, type PageKey } from "./routing";
import { sortByPinyin, sortByPinyinName } from "./sort";
import { filterTagMatches, resolveExistingTag } from "./tagPicker";
import {
  delay,
  formatBytes,
  formatCodecs,
  formatDate,
  formatPhotoDate,
  formatDurationSeconds,
  formatResolution,
  getFileExtension,
  getVideoFormatLabel,
  isSupportedVideoFile,
  isTextEditingTarget,
  isVideoCodecMissing,
  isVideoMetadataRepairPending,
  splitCommaList,
  subtitleAsrStatusLabel,
  subtitleServiceStatusLabel,
  subtitleTrackStatusLabel,
  supportedVideoAccept,
  supportedVideoFormatLabel,
  videoLongPressDelayMs,
  videoLongPressRate,
  videoPartSize,
  videoPartUploadMaxAttempts,
  videoPartUploadRetryDelayMs,
  videoResumeStorageKey as legacyVideoResumeStorageKey,
  videoSeekLargeSeconds,
  videoSeekSeconds,
  videoStatusLabel,
  videoUploadQueueStorageKey,
  withImageWidth
} from "./utils";
import {
  loadStoredVideoUploadQueue,
  makeVideoQueueItem,
  saveStoredVideoUploadQueue,
  videoFileFingerprint,
  videoQueueStatusLabel,
  type VideoUploadQueueItem,
  type VideoUploadQueueStatus
} from "./videoUploadQueue";
import {
  addGalleryPhotoPerson,
  addGalleryPhotoTag,
  addPersonSamples,
  batchDeleteGalleryPhotos,
  batchDeletePersons,
  bindPersonTag,
  cancelVideoUpload,
  completeVideoUpload,
  createPerson,
  createVideoCategoryTag,
  createVideoPerson,
  createVideoUploadSession,
  deleteGalleryPhoto,
  deleteGalleryPhotoPerson,
  deleteGalleryPhotoTag,
  deletePerson,
  deletePersonSample,
  deleteVideo,
  deleteVideoCategoryTag,
  deleteVideoPerson,
  cancelVideoSubtitles,
  generateVideoSubtitles,
  getSubtitleServiceLogs,
  getSubtitleServiceStatus,
  getVideo,
  getVideoPlaybackDiagnostics,
  getVideoUploadSession,
  getGalleryExportUrl,
  getGalleryPhoto,
  getPersonExportUrl,
  getTask,
  importGalleryExportZip,
  importGalleryPhotos,
  importGalleryRichPhotos,
  importPersonSamples,
  listGalleryPhotos,
  listPersonSamples,
  listPersons,
  listPersonTags,
  listTags,
  listSubtitleJobs,
  listVideoCategoryTags,
  listVideoPeople,
  listVideos,
  renamePerson,
  replaceVideoCover,
  optimizeVideoPlayback,
  promoteGalleryPhotoPersonSample,
  undoGalleryPhotoPersonSample,
  reRecognizeGalleryPhoto,
  reRecognizeUnknownGalleryPhotos,
  updateGalleryPhotoRichText,
  uploadVideoPart,
  unbindPersonTag,
  updateVideo,
  addVideoCategoryTag,
  removeVideoCategoryTag,
  addVideoPerson,
  removeVideoPerson,
  startSubtitleService,
  stopSubtitleService,
  updateVideoCategoryTag,
  updateVideoPerson,
  type GalleryExportScope,
  type GalleryUploadMetadata
} from "./api/index";
import type {
  AuthSession,
  GalleryPhotoDetail,
  GalleryPhotoListItem,
  Person,
  SamplePhoto,
  SubtitleJob,
  SubtitleServiceLogs,
  SubtitleServiceStatus,
  Tag,
  Task,
  VideoCategoryTag,
  VideoDetail,
  VideoItem,
  VideoPlaybackDiagnostics,
  VideoPerson,
  VideoUploadSession,
} from "./types";

function isSystemUnknownPerson(person: Person | null | undefined): boolean {
  return Boolean(person?.is_unknown && person.display_name === systemUnknownPersonName);
}

const galleryPageSize = 20;
const videoPageSize = 24;
const systemUnknownPersonName = "未知人物";
const compactGalleryMediaQuery = "(max-width: 1600px)";

type GalleryDrawer = "filter" | "detail" | null;

type MainAppProps = {
  authSession: AuthSession;
  onLogout: () => void;
  onSessionChange: (session: AuthSession) => void;
};

export function ApplicationContent({ authSession, onLogout, onSessionChange }: MainAppProps) {
  const confirm = useConfirm();
  const [page, setPageState] = useState<PageKey>(() => routeFromHash());
  const [workspacePanelOpen, setWorkspacePanelOpen] = useState(false);
  const [playVideoId, setPlayVideoId] = useState<string | null>(null);
  const [isVideoUploadModalOpen, setIsVideoUploadModalOpen] = useState(false);
  const [persons, setPersons] = useState<Person[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const gallery = useGalleryController({ persons, tags });
  const {
    galleryPhotos, setGalleryPhotos, galleryTotal, setGalleryTotal, galleryOffset, setGalleryOffset,
    gallerySelectionMode, setGallerySelectionMode, selectedGalleryPhotoIds, setSelectedGalleryPhotoIds,
    galleryExportModalOpen, setGalleryExportModalOpen, galleryExportScope, setGalleryExportScope,
    galleryExportPersonIds, setGalleryExportPersonIds, galleryExportTagIds, setGalleryExportTagIds,
    lightboxPhotoId, setLightboxPhotoId, selectedPersonIds, setSelectedPersonIds, selectedTagIds,
    setSelectedTagIds, excludePersonIds, setExcludePersonIds, excludeTagIds, setExcludeTagIds,
    personSearch, setPersonSearch, tagSearch, setTagSearch, showUnknownPersons, setShowUnknownPersons,
    showExcludePersons, setShowExcludePersons, showExcludeTags, setShowExcludeTags, richTag, normalTags,
    filteredPersons, selectedFilterPersons, knownFilterPersons, unknownFilterPersons, allFilteredUnknownPersons,
    personSearchActive, visibleUnknownFilterPersons, selectedUnknownPersonCount, allFilteredUnknownSelected,
    filteredTags, excludedFilterPersons, excludedFilterTags, availableExcludePersons, availableExcludeKnownPersons,
    availableExcludeUnknownPersons, availableExcludeTags
  } = gallery;
  const [selectedPhoto, setSelectedPhoto] = useState<GalleryPhotoDetail | null>(null);
  const [galleryDrawer, setGalleryDrawer] = useState<GalleryDrawer>(null);
  const [galleryCompact, setGalleryCompact] = useState(() => window.matchMedia(compactGalleryMediaQuery).matches);
  const [manualPersonId, setManualPersonId] = useState("");
  const [manualPersonSearch, setManualPersonSearch] = useState("");
  const [manualPersonNotice, setManualPersonNotice] = useState<string | null>(null);
  const [manualTagId, setManualTagId] = useState("");
  const [manualTagSearch, setManualTagSearch] = useState("");
  const [manualTagNotice, setManualTagNotice] = useState<string | null>(null);
  const [manualTagName, setManualTagName] = useState("");
  const [richTextDraft, setRichTextDraft] = useState("");
  const [lightboxRichTextDraft, setLightboxRichTextDraft] = useState("");
  const [lightboxEditMode, setLightboxEditMode] = useState(false);
  const people = usePeopleController({ persons });
  const {
    selectedPerson, setSelectedPerson, peopleSearch, setPeopleSearch, peopleBatchDeleteMode,
    setPeopleBatchDeleteMode, selectedPersonDeleteIds, setSelectedPersonDeleteIds, samples, setSamples,
    personTags, setPersonTags, personTagSelectId, setPersonTagSelectId, personTagName, setPersonTagName,
    newPersonName, setNewPersonName, renameValue, setRenameValue, task, setTask, recognitionNotice,
    setRecognitionNotice, filteredPeopleInLibrary, unknownPersonCount
  } = people;
  const upload = useUploadController();
  const {
    pendingSampleUploads, setPendingSampleUploads, pendingGalleryUploads, setPendingGalleryUploads,
    batchApplyPersonNames, setBatchApplyPersonNames, batchApplyTagNames, setBatchApplyTagNames,
    uploadMode, setUploadMode, galleryUploadBusy, setGalleryUploadBusy, importTask, setImportTask,
    galleryImportTask, setGalleryImportTask
  } = upload;
  const video = useVideoController();
  const {
    videoItems, setVideoItems, videoTotal, setVideoTotal, videoOffset, setVideoOffset,
    videoCategoryTags, setVideoCategoryTags, videoPeople, setVideoPeople, selectedVideoCategoryIds,
    setSelectedVideoCategoryIds, selectedVideoPersonIds, setSelectedVideoPersonIds, videoSearch,
    setVideoSearch, selectedVideo, setSelectedVideo, selectedVideoCodecRepairVideoId,
    selectedVideoCodecRepairPolls, videoPlayerUrl, setVideoPlayerUrl, videoPlaybackDiagnostics,
    setVideoPlaybackDiagnostics, videoPlaybackDiagnosticsLoading, setVideoPlaybackDiagnosticsLoading,
    videoFiles, setVideoFiles, videoTitle, setVideoTitle, videoDescription, setVideoDescription,
    videoUploadCategoryIds, setVideoUploadCategoryIds, videoUploadPersonIds, setVideoUploadPersonIds,
    videoUploadNewCategories, setVideoUploadNewCategories, videoUploadGenerateSubtitles,
    setVideoUploadGenerateSubtitles, videoUploadProgress, setVideoUploadProgress, videoUploadSession,
    setVideoUploadSession, videoUploadCurrentIndex, setVideoUploadCurrentIndex, videoUploadTotalCount,
    setVideoUploadTotalCount, videoUploadBusy, setVideoUploadBusy, videoUploadQueue, setVideoUploadQueue,
    videoUploadQueueRef, newVideoCategoryName, setNewVideoCategoryName, newVideoPersonName,
    setNewVideoPersonName, newVideoPersonNote, setNewVideoPersonNote, newVideoPersonAvatar,
    setNewVideoPersonAvatar, isVideoEditModalOpen, setIsVideoEditModalOpen, editVideoTitle,
    setEditVideoTitle, editVideoDescription, setEditVideoDescription, editVideoCategoryIds,
    setEditVideoCategoryIds, editVideoPersonIds, setEditVideoPersonIds, isCategoryManageModalOpen,
    setIsCategoryManageModalOpen, isVideoPersonManageModalOpen, setIsVideoPersonManageModalOpen,
    editingCategoryId, setEditingCategoryId, editingCategoryName, setEditingCategoryName,
    newManageCategoryName, setNewManageCategoryName, editingPersonId, setEditingPersonId,
    editingPersonName, setEditingPersonName, editingPersonNote, setEditingPersonNote,
    editingPersonAvatar, setEditingPersonAvatar, newManagePersonName, setNewManagePersonName,
    newManagePersonNote, setNewManagePersonNote, newManagePersonAvatar, setNewManagePersonAvatar,
    filteredVideoCategoryTags, filteredVideoPeople, selectedVideoCategories, selectedVideoPeople
  } = video;
  const previousPageRef = useRef<PageKey>(page);
  const subtitle = useSubtitleController();
  const {
    subtitleServiceStatus, setSubtitleServiceStatus, subtitleServiceLogs, setSubtitleServiceLogs,
    subtitleJobs, setSubtitleJobs, subtitleJobsLoaded, setSubtitleJobsLoaded, subtitleServiceBusy,
    setSubtitleServiceBusy, subtitleServiceNotice, setSubtitleServiceNotice, subtitleLogsOpen,
    setSubtitleLogsOpen, activeSubtitleJobs, visibleSubtitleJobs
  } = subtitle;
  const importFileRef = useRef<HTMLInputElement | null>(null);
  const galleryImportFileRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jumpPageInput, setJumpPageInput] = useState("");
  const peopleMainRef = useRef<HTMLElement | null>(null);
  const galleryFilterRef = useRef<HTMLElement | null>(null);
  const galleryDetailRef = useRef<HTMLElement | null>(null);
  const galleryFilterTriggerRef = useRef<HTMLButtonElement | null>(null);
  const galleryFilterCloseRef = useRef<HTMLButtonElement | null>(null);
  const galleryDetailCloseRef = useRef<HTMLButtonElement | null>(null);
  const galleryDrawerReturnFocusRef = useRef<HTMLElement | null>(null);

  const selectedPersonIsSystemUnknown = isSystemUnknownPerson(selectedPerson);

  const selectedPersonDeleteCount = useMemo(
    () => selectedPersonDeleteIds.filter((id) => !isSystemUnknownPerson(persons.find((person) => person.id === id))).length,
    [persons, selectedPersonDeleteIds]
  );
  const galleryFilterCount = selectedPersonIds.length + selectedTagIds.length + excludePersonIds.length + excludeTagIds.length;

  const videoTotalPages = Math.max(1, Math.ceil(videoTotal / videoPageSize));
  const videoCurrentPage = Math.floor(videoOffset / videoPageSize) + 1;
  const selectedVideoSubtitlePollingKey =
    selectedVideo?.subtitle_tracks.map((track) => `${track.id}:${track.status}`).join("|") ?? "";
  const activeSubtitleJobCount = activeSubtitleJobs.length;

  async function refreshPeople() {
    const nextPersons = await listPersons();
    setPersons(nextPersons);
    setSelectedPersonDeleteIds((current) => current.filter((id) => nextPersons.some((person) => person.id === id)));
    setSelectedPerson((current) => {
      if (!current) {
        return nextPersons[0] ?? null;
      }
      return nextPersons.find((person) => person.id === current.id) ?? nextPersons[0] ?? null;
    });
  }

  async function refreshTags() {
    setTags(sortByPinyinName(await listTags()));
  }

  async function refreshGallery(
    nextOffset = galleryOffset,
    personIds = selectedPersonIds,
    tagIds = selectedTagIds,
    nextExcludePersonIds?: number[],
    nextExcludeTagIds?: number[],
  ) {
    const epIds = nextExcludePersonIds ?? excludePersonIds;
    const etIds = nextExcludeTagIds ?? excludeTagIds;
    const response = await listGalleryPhotos(personIds, tagIds, epIds, etIds, nextOffset, galleryPageSize);
    setGalleryPhotos(response.items);
    setGalleryTotal(response.total);
    setGalleryOffset(response.offset);
    setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
  }

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
  ) {
    const response = await listVideos(categoryIds, personIds, query, nextOffset, videoPageSize);
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

  async function refreshSamples(personId: number | null) {
    if (!personId) {
      setSamples([]);
      return;
    }
    setSamples(await listPersonSamples(personId));
  }

  async function refreshPersonTags(personId: number | null) {
    if (!personId) {
      setPersonTags([]);
      return;
    }
    setPersonTags(sortByPinyinName(await listPersonTags(personId)));
  }

  function openGalleryDrawer(nextDrawer: Exclude<GalleryDrawer, null>) {
    if (!window.matchMedia(compactGalleryMediaQuery).matches) {
      return;
    }
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && activeElement !== document.body) {
      galleryDrawerReturnFocusRef.current = activeElement;
    } else {
      galleryDrawerReturnFocusRef.current = galleryFilterTriggerRef.current;
    }
    setGalleryDrawer(nextDrawer);
  }

  function closeGalleryDrawer(restoreFocus = true) {
    setGalleryDrawer(null);
    if (!restoreFocus) {
      return;
    }
    window.requestAnimationFrame(() => {
      const returnTarget = galleryDrawerReturnFocusRef.current;
      galleryDrawerReturnFocusRef.current = null;
      if (returnTarget?.isConnected) {
        returnTarget.focus();
      } else {
        galleryFilterTriggerRef.current?.focus();
      }
    });
  }

  useEffect(() => {
    const mediaQuery = window.matchMedia(compactGalleryMediaQuery);
    const handleChange = () => {
      setGalleryCompact(mediaQuery.matches);
      if (!mediaQuery.matches) {
        setGalleryDrawer(null);
      }
    };
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (page !== "gallery") {
      setGalleryDrawer(null);
    }
  }, [page]);

  useEffect(() => {
    galleryFilterRef.current?.toggleAttribute("inert", galleryCompact && galleryDrawer !== "filter");
    galleryDetailRef.current?.toggleAttribute("inert", galleryCompact && galleryDrawer !== "detail");
  }, [galleryCompact, galleryDrawer, page]);

  useEffect(() => {
    if (!galleryCompact || !galleryDrawer) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const panel = galleryDrawer === "filter" ? galleryFilterRef.current : galleryDetailRef.current;
    const closeButton = galleryDrawer === "filter" ? galleryFilterCloseRef.current : galleryDetailCloseRef.current;
    document.body.style.overflow = "hidden";
    window.requestAnimationFrame(() => closeButton?.focus());

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeGalleryDrawer();
        return;
      }
      if (event.key !== "Tab" || !panel) {
        return;
      }
      const focusableElements = Array.from(
        panel.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter((element) => element.getClientRects().length > 0);
      if (focusableElements.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const firstElement = focusableElements[0];
      const lastElement = focusableElements[focusableElements.length - 1];
      if (event.shiftKey && (document.activeElement === firstElement || document.activeElement === panel)) {
        event.preventDefault();
        lastElement.focus();
      } else if (!event.shiftKey && document.activeElement === lastElement) {
        event.preventDefault();
        firstElement.focus();
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [galleryCompact, galleryDrawer]);

  function handleTogglePersonFilter(personId: number) {
    const active = selectedPersonIds.includes(personId);
    const next = active ? selectedPersonIds.filter((id) => id !== personId) : [...selectedPersonIds, personId];
    setSelectedPersonIds(next);
    let nextExclude = excludePersonIds;
    if (!active && excludePersonIds.includes(personId)) {
      nextExclude = excludePersonIds.filter((id) => id !== personId);
      setExcludePersonIds(nextExclude);
    }
    void refreshGallery(0, next, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleToggleUnknownPersonFilters() {
    const targetIds = allFilteredUnknownPersons.map((person) => person.id);
    if (targetIds.length === 0) {
      return;
    }
    const targetIdSet = new Set(targetIds);
    const next = allFilteredUnknownSelected
      ? selectedPersonIds.filter((id) => !targetIdSet.has(id))
      : Array.from(new Set([...selectedPersonIds, ...targetIds]));
    setSelectedPersonIds(next);
    setShowUnknownPersons(true);
    let nextExclude = excludePersonIds;
    if (!allFilteredUnknownSelected) {
      nextExclude = excludePersonIds.filter((id) => !targetIdSet.has(id));
      setExcludePersonIds(nextExclude);
    }
    void refreshGallery(0, next, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleToggleExcludePerson(personId: number) {
    const active = excludePersonIds.includes(personId);
    let nextExclude: number[];
    let nextInclude = selectedPersonIds;
    if (active) {
      nextExclude = excludePersonIds.filter((id) => id !== personId);
    } else {
      nextExclude = [...excludePersonIds, personId];
      if (selectedPersonIds.includes(personId)) {
        nextInclude = selectedPersonIds.filter((id) => id !== personId);
        setSelectedPersonIds(nextInclude);
      }
    }
    setExcludePersonIds(nextExclude);
    void refreshGallery(0, nextInclude, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleToggleExcludeTag(tagId: number) {
    const active = excludeTagIds.includes(tagId);
    let nextExclude: number[];
    let nextInclude = selectedTagIds;
    if (active) {
      nextExclude = excludeTagIds.filter((id) => id !== tagId);
    } else {
      nextExclude = [...excludeTagIds, tagId];
      if (selectedTagIds.includes(tagId)) {
        nextInclude = selectedTagIds.filter((id) => id !== tagId);
        setSelectedTagIds(nextInclude);
      }
    }
    setExcludeTagIds(nextExclude);
    void refreshGallery(0, selectedPersonIds, nextInclude, excludePersonIds, nextExclude);
  }

  useEffect(() => {
    if (!recognitionNotice) {
      return;
    }
    const timer = window.setTimeout(() => setRecognitionNotice(null), 5000);
    return () => window.clearTimeout(timer);
  }, [recognitionNotice]);

  useEffect(() => {
    const onHashChange = () => {
      const newPage = routeFromHash();
      setPageState(newPage);
      if (newPage === "video-play") {
        const hash = window.location.hash.replace(/^#\/?/, "");
        const id = hash.split("/")[1];
        if (id) {
          const numId = parseInt(id, 10);
          setPlayVideoId(id);
          void openVideo(numId);
        }
      }
    };
    window.addEventListener("hashchange", onHashChange);
    // Initial check
    if (!window.location.hash) {
      setRoute("home");
    } else {
      // Call it once to handle deep links correctly (avoid multiple fires but ensure playVideoId is set)
      const initialPage = routeFromHash();
      if (initialPage === "video-play") {
        onHashChange();
      }
    }
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshPeople(), refreshTags(), refreshGallery(0, [], [])]);
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "初始化数据失败。");
      }
    })();
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        await Promise.all([refreshVideoTaxonomy(), refreshVideos(0, [], [], "")]);
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
    if (!videoUploadBusy) {
      return undefined;
    }
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, [videoUploadBusy]);

  useEffect(() => {
    if (page === "videos" && previousPageRef.current !== "videos") {
      void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
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


  useEffect(() => {
    void refreshSamples(selectedPerson?.id ?? null);
    void refreshPersonTags(selectedPerson?.id ?? null);
    if (selectedPerson) {
      setRenameValue(selectedPerson.display_name);
      setPersonTagSelectId("");
      setPersonTagName("");
    }
  }, [selectedPerson]);

  useEffect(() => {
    if (!task || task.status === "completed" || task.status === "failed" || task.status === "canceled") {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(task.id);
        setTask(nextTask);
        if (nextTask.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery(0, selectedPersonIds, selectedTagIds)]);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "任务轮询失败。");
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [selectedPersonIds, selectedTagIds, task]);

  useEffect(() => {
    if (!importTask || importTask.status === "completed" || importTask.status === "failed" || importTask.status === "canceled") {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(importTask.id);
        setImportTask(nextTask);
        if (nextTask.status === "completed") {
          await refreshPeople();
          setBusy(false);
        }
        if (nextTask.status === "failed") {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "导入轮询失败。");
        setBusy(false);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [importTask]);

  useEffect(() => {
    if (
      !galleryImportTask ||
      galleryImportTask.status === "completed" ||
      galleryImportTask.status === "failed" ||
      galleryImportTask.status === "canceled"
    ) {
      return undefined;
    }
    const timer = window.setInterval(async () => {
      try {
        const nextTask = await getTask(galleryImportTask.id);
        setGalleryImportTask(nextTask);
        if (nextTask.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
          setBusy(false);
        }
        if (nextTask.status === "failed") {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "展示图 ZIP 导入轮询失败。");
        setBusy(false);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [galleryImportTask, galleryOffset, selectedPersonIds, selectedTagIds]);

  async function openGalleryPhoto(photoId: number) {
    setError(null);
    try {
      const detail = await getGalleryPhoto(photoId);
      setSelectedPhoto(detail);
      setRichTextDraft(detail.rich_text ?? "");
      setManualPersonId("");
      setManualPersonSearch("");
      setManualPersonNotice(null);
      setManualTagId("");
      setManualTagSearch("");
      setManualTagNotice(null);
      setManualTagName("");
      openGalleryDrawer("detail");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载图片详情失败。");
    }
  }

  function openGalleryLightbox(photoId: number) {
    setLightboxPhotoId(photoId);
  }

  function closeGalleryLightbox() {
    setLightboxPhotoId(null);
    setLightboxEditMode(false);
  }

  function scrollToPageTop() {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function openLightboxPhotoDetail() {
    if (!lightboxPhoto) {
      return;
    }
    const photoId = lightboxPhoto.id;
    closeGalleryLightbox();
    await openGalleryPhoto(photoId);
    if (!window.matchMedia(compactGalleryMediaQuery).matches) {
      window.setTimeout(() => {
        galleryDetailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 0);
    }
  }

  async function handleCreatePerson() {
    if (!newPersonName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const person = await createPerson(newPersonName.trim());
      setNewPersonName("");
      await refreshPeople();
      setSelectedPerson(person);
      setPageState("people");
      setRoute("people");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "创建人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleRenamePerson() {
    if (!selectedPerson || !renameValue.trim()) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能改名，请在图库详情中重新识别或改为已有正式人物。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const updated = await renamePerson(selectedPerson.id, renameValue.trim());
      await refreshPeople();
      setSelectedPerson(updated);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "人物改名失败。");
    } finally {
      setBusy(false);
    }
  }

  function handlePickSampleFiles(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能上传样本图。");
      return;
    }
    setPendingSampleUploads((current) => [
      ...current,
      ...Array.from(files).map((file) => ({ file, previewUrl: URL.createObjectURL(file) }))
    ]);
  }

  async function handleConfirmSampleUpload() {
    if (!selectedPerson || pendingSampleUploads.length === 0) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能上传样本图。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await addPersonSamples(
        selectedPerson.id,
        pendingSampleUploads.map((item) => item.file)
      );
      pendingSampleUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      setPendingSampleUploads([]);
      await Promise.all([refreshPeople(), refreshSamples(selectedPerson.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "样本上传失败。");
    } finally {
      setBusy(false);
    }
  }

  function handleRemovePendingSample(index: number) {
    setPendingSampleUploads((current) => {
      const target = current[index];
      if (target) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((_, i) => i !== index);
    });
  }

  async function handleDeleteSample(samplePhotoId: number) {
    if (!selectedPerson) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deletePersonSample(selectedPerson.id, samplePhotoId);
      await Promise.all([refreshPeople(), refreshSamples(selectedPerson.id)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除样本失败。");
    } finally {
      setBusy(false);
    }
  }

  function togglePeopleBatchDeleteMode() {
    setPeopleBatchDeleteMode((current) => {
      if (current) {
        setSelectedPersonDeleteIds([]);
      }
      return !current;
    });
  }

  async function handleDeleteSelectedPersons() {
    if (selectedPersonDeleteIds.length === 0) {
      return;
    }
    const deletableIds = selectedPersonDeleteIds.filter((id) => !isSystemUnknownPerson(persons.find((person) => person.id === id)));
    if (deletableIds.length === 0) {
      setError("系统未知人物不能删除。");
      return;
    }
    if (!await confirm({ title: "删除人物", message: `确认删除选中的 ${deletableIds.length} 个人物吗？这会删除其样本图、关联向量与对象存储文件。`, confirmLabel: "删除", tone: "danger" })) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeletePersons(deletableIds);
      setSelectedPersonDeleteIds([]);
      setPeopleBatchDeleteMode(false);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量删除人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCurrentPerson() {
    if (!selectedPerson) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能删除。");
      return;
    }
    if (!await confirm({ title: "删除人物", message: `确认删除人物「${selectedPerson.display_name}」吗？`, confirmLabel: "删除", tone: "danger" })) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deletePerson(selectedPerson.id);
      setSelectedPersonDeleteIds((current) => current.filter((id) => id !== selectedPerson.id));
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleReRecognizeAllUnknownPhotos() {
    if (
      !await confirm({ title: "重新识别未知人物", message: "确认重新识别所有带未知人物标签的图片吗？识别后的新人物标签会覆盖旧标签。", confirmLabel: "开始识别" })
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await reRecognizeUnknownGalleryPhotos();
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
      if (selectedPhoto) {
        const detail = await getGalleryPhoto(selectedPhoto.id);
        setSelectedPhoto(detail);
      }
      window.alert(`已完成重新识别：共 ${result.total} 张，成功 ${result.succeeded} 张，失败 ${result.failed} 张。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量重新识别未知人物失败。");
    } finally {
      setBusy(false);
    }
  }

  function handleExportPersons() {
    window.open(getPersonExportUrl(), "_blank");
  }

  function handlePickImportFile() {
    importFileRef.current?.click();
  }

  async function handleImportFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const task = await importPersonSamples(file);
      setImportTask(task);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败。");
      setBusy(false);
    }
    if (event.target) {
      event.target.value = "";
    }
  }

  function handleExportGalleryPhotos() {
    const url = getGalleryExportUrl({
      scope: galleryExportScope,
      personIds: galleryExportPersonIds,
      tagIds: galleryExportTagIds
    });
    window.open(url, "_blank");
    setGalleryExportModalOpen(false);
  }

  function openGalleryExportModal() {
    setGalleryExportScope("filtered");
    setGalleryExportPersonIds(selectedPersonIds);
    setGalleryExportTagIds(selectedTagIds.filter((tagId) => tags.some((tag) => tag.id === tagId && !tag.is_system)));
    setGalleryExportModalOpen(true);
  }

  function handleToggleGalleryExportPerson(personId: number) {
    setGalleryExportScope("filtered");
    setGalleryExportPersonIds((current) =>
      current.includes(personId) ? current.filter((id) => id !== personId) : [...current, personId]
    );
  }

  function handleToggleGalleryExportTag(tagId: number) {
    setGalleryExportScope("filtered");
    setGalleryExportTagIds((current) =>
      current.includes(tagId) ? current.filter((id) => id !== tagId) : [...current, tagId]
    );
  }

  function handlePickGalleryImportFile() {
    galleryImportFileRef.current?.click();
  }

  async function handleGalleryImportFileChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const task = await importGalleryExportZip(file);
      setGalleryImportTask(task);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "展示图 ZIP 导入失败。");
      setBusy(false);
    }
    if (event.target) {
      event.target.value = "";
    }
  }

  function handleSelectPerson(person: Person) {
    pendingSampleUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    setPendingSampleUploads([]);
    setSelectedPerson(person);
    if (window.matchMedia("(max-width: 1240px)").matches) {
      window.requestAnimationFrame(() => {
        peopleMainRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    }
  }

  async function handleBindPersonTag() {
    if (!selectedPerson || (!personTagSelectId && !personTagName.trim())) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能维护普通标签。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await bindPersonTag(
        selectedPerson.id,
        personTagSelectId ? { tagId: Number(personTagSelectId) } : { name: personTagName.trim() }
      );
      setPersonTags(sortByPinyinName(next));
      setPersonTagSelectId("");
      setPersonTagName("");
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "人物标签绑定失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUnbindPersonTag(tagId: number) {
    if (!selectedPerson) {
      return;
    }
    if (selectedPersonIsSystemUnknown) {
      setError("系统未知人物不能维护普通标签。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const next = await unbindPersonTag(selectedPerson.id, tagId);
      setPersonTags(sortByPinyinName(next));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "人物标签移除失败。");
    } finally {
      setBusy(false);
    }
  }

  function handlePickGalleryFiles(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    setPendingGalleryUploads((current) => [
      ...current,
      ...Array.from(files).map((file) => ({
        file,
        previewUrl: URL.createObjectURL(file),
        personNamesText: "",
        tagNamesText: "",
        richText: ""
      }))
    ]);
  }

  function handleUpdatePendingGallery(index: number, changes: Partial<PendingGalleryUpload>) {
    setPendingGalleryUploads((current) =>
      current.map((item, i) => {
        if (i !== index) {
          return item;
        }
        return { ...item, ...changes };
      })
    );
  }

  function handleApplyBatchMetadataToAll() {
    const personNames = splitCommaList(batchApplyPersonNames);
    const tagNames = splitCommaList(batchApplyTagNames);
    if (personNames.length === 0 && tagNames.length === 0) {
      return;
    }
    setPendingGalleryUploads((current) =>
      current.map((item) => {
        const mergedPersons = Array.from(new Set([...splitCommaList(item.personNamesText), ...personNames]));
        const mergedTags = Array.from(new Set([...splitCommaList(item.tagNamesText), ...tagNames]));
        return {
          ...item,
          personNamesText: mergedPersons.join(", "),
          tagNamesText: mergedTags.join(", ")
        };
      })
    );
  }

  function handleRemovePendingGallery(index: number) {
    setPendingGalleryUploads((current) => {
      const target = current[index];
      if (target) {
        URL.revokeObjectURL(target.previewUrl);
      }
      return current.filter((_, i) => i !== index);
    });
  }

  async function handleConfirmGalleryUpload() {
    if (pendingGalleryUploads.length === 0) {
      return;
    }
    setGalleryUploadBusy(true);
    setError(null);
    try {
      const files = pendingGalleryUploads.map((item) => item.file);
      const metadata: GalleryUploadMetadata[] = pendingGalleryUploads.map((item) => ({
        person_names: splitCommaList(item.personNamesText),
        tag_names: splitCommaList(item.tagNamesText),
        rich_text: uploadMode === "rich" ? item.richText.trim() : undefined
      }));
      const nextTask =
        uploadMode === "rich" ? await importGalleryRichPhotos(files, metadata) : await importGalleryPhotos(files, metadata);
      setTask(nextTask);
      pendingGalleryUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      setPendingGalleryUploads([]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "展示图上传失败。");
    } finally {
      setGalleryUploadBusy(false);
    }
  }

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
      generateZhSubtitles: videoUploadGenerateSubtitles
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
    void refreshVideos(0, next, selectedVideoPersonIds, videoSearch);
  }

  function handleToggleVideoFilterPerson(personId: number) {
    const next = selectedVideoPersonIds.includes(personId)
      ? selectedVideoPersonIds.filter((id) => id !== personId)
      : [...selectedVideoPersonIds, personId];
    setSelectedVideoPersonIds(next);
    void refreshVideos(0, selectedVideoCategoryIds, next, videoSearch);
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


  async function handleDeleteCurrentVideo(): Promise<boolean> {
    if (!selectedVideo) {
      return false;
    }
    if (!await confirm({ title: "删除视频", message: `确认删除视频「${selectedVideo.title}」吗？`, confirmLabel: "删除", tone: "danger" })) {
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteVideo(selectedVideo.id);
      setSelectedVideo(null);
      setVideoPlayerUrl("");
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
      return true;
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除视频失败。");
      return false;
    } finally {
      setBusy(false);
    }
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

  function openVideoEditModal() {
    if (!selectedVideo) return;
    setEditVideoTitle(selectedVideo.title);
    setEditVideoDescription(selectedVideo.description || "");
    setEditVideoCategoryIds(selectedVideo.category_tags.map(t => t.id));
    setEditVideoPersonIds(selectedVideo.people.map(p => p.id));
    setIsVideoEditModalOpen(true);
  }

  async function handleSaveVideoEdit() {
    if (!selectedVideo) return;
    setBusy(true);
    setError(null);
    try {
      await updateVideo(selectedVideo.id, {
        title: editVideoTitle.trim() || selectedVideo.title,
        description: editVideoDescription.trim() || null
      });
      const oldCategoryIds = new Set(selectedVideo.category_tags.map(t => t.id));
      const newCategoryIds = new Set(editVideoCategoryIds);
      for (const tagId of editVideoCategoryIds) {
        if (!oldCategoryIds.has(tagId)) {
          await addVideoCategoryTag(selectedVideo.id, { tagId });
        }
      }
      for (const tagId of selectedVideo.category_tags.map(t => t.id)) {
        if (!newCategoryIds.has(tagId)) {
          await removeVideoCategoryTag(selectedVideo.id, tagId);
        }
      }
      const oldPersonIds = new Set(selectedVideo.people.map(p => p.id));
      const newPersonIds = new Set(editVideoPersonIds);
      for (const personId of editVideoPersonIds) {
        if (!oldPersonIds.has(personId)) {
          await addVideoPerson(selectedVideo.id, personId);
        }
      }
      for (const personId of selectedVideo.people.map(p => p.id)) {
        if (!newPersonIds.has(personId)) {
          await removeVideoPerson(selectedVideo.id, personId);
        }
      }
      const detail = await getVideo(selectedVideo.id);
      setSelectedVideo(detail);
      setVideoItems((items) => items.map((item) => (item.id === detail.id ? { ...item, ...detail } : item)));
      setIsVideoEditModalOpen(false);
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
      console.log(`[批量上传] 第 ${fileIndex + 1}/${totalCount} 个: ${file.name} (${file.size} bytes)`);

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
        session = await getVideoUploadSession(session.id);
        setVideoUploadSession(session);
        const detail = await completeVideoUpload(session.id, {
          category_tag_ids: item.categoryTagIds,
          category_tag_names: item.categoryTagNames,
          person_ids: item.personIds,
          generate_zh_subtitles: item.generateZhSubtitles
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
        console.log(`[批量上传] 第 ${fileIndex + 1}/${totalCount} 个完成: ${file.name}`);
      } catch (cause) {
        const message = cause instanceof Error ? cause.message : "视频上传失败。";
        lastError = `"${file.name}" ${message}`;
        syncWorkingQueueItem(item.id, { status: "failed", error: message });
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
      void refreshVideoTaxonomy();
      void refreshVideos(0, [], [], "");
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
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
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
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
      if (selectedVideo?.id === job.video_id) {
        setSelectedVideo(await getVideo(job.video_id));
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消字幕任务失败。");
    } finally {
      setSubtitleServiceBusy(false);
    }
  }

  async function handleAddPhotoPerson() {
    if (!selectedPhoto || !manualPersonSearch.trim()) {
      return;
    }
    const person = resolveExistingPerson(availablePersonsForPhoto, manualPersonSearch, manualPersonId);
    if (!person) {
      const matches = filterPersonMatches(availablePersonsForPhoto, manualPersonSearch);
      setManualPersonNotice(
        matches.length > 0
          ? "请从匹配结果中选择一个具体人物。"
          : `人物“${manualPersonSearch.trim()}”不存在，请先在人物样本页创建人物。`
      );
      return;
    }
    setBusy(true);
    setError(null);
    setManualPersonNotice(null);
    try {
      const result = await addGalleryPhotoPerson(selectedPhoto.id, person.id);
      setSelectedPhoto(result);
      setManualPersonId("");
      setManualPersonSearch("");
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加人物标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handlePromotePhotoPerson(personId: number) {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await promoteGalleryPhotoPersonSample(selectedPhoto.id, personId);
      setSelectedPhoto(result);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加入人物样本库失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUndoPromotePhotoPerson(personId: number) {
    if (!selectedPhoto || !await confirm({ title: "撤销人物样本", message: "确定撤销这个图库人脸样本吗？图库图片和人物标签会保留。", confirmLabel: "撤销", tone: "danger" })) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await undoGalleryPhotoPersonSample(selectedPhoto.id, personId);
      setSelectedPhoto(result);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "撤销人物样本失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleOpenSampleSource(photoId: number) {
    setPageState("gallery");
    setRoute("gallery");
    await openGalleryPhoto(photoId);
    if (!window.matchMedia(compactGalleryMediaQuery).matches) {
      window.setTimeout(() => galleryDetailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }), 0);
    }
  }

  async function handleDeletePhotoPerson(personId: number) {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await deleteGalleryPhotoPerson(selectedPhoto.id, personId);
      setSelectedPhoto(detail);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除人物标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddExistingPhotoTag() {
    if (!selectedPhoto || !manualTagSearch.trim()) {
      return;
    }
    const tag = resolveExistingTag(availableTagsForPhoto, manualTagSearch, manualTagId);
    if (!tag) {
      const matches = filterTagMatches(availableTagsForPhoto, manualTagSearch);
      setManualTagNotice(
        matches.length > 0
          ? "请从匹配结果中选择一个具体标签。"
          : `标签“${manualTagSearch.trim()}”不存在，请先在下方创建标签。`
      );
      return;
    }
    setBusy(true);
    setError(null);
    setManualTagNotice(null);
    try {
      const detail = await addGalleryPhotoTag(selectedPhoto.id, { tagId: tag.id });
      setSelectedPhoto(detail);
      setManualTagId("");
      setManualTagSearch("");
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateAndAddPhotoTag() {
    if (!selectedPhoto || !manualTagName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    setManualTagNotice(null);
    try {
      const detail = await addGalleryPhotoTag(selectedPhoto.id, { name: manualTagName.trim() });
      setSelectedPhoto(detail);
      setManualTagName("");
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeletePhotoTag(tagId: number) {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await deleteGalleryPhotoTag(selectedPhoto.id, tagId);
      setSelectedPhoto(detail);
      await Promise.all([refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveRichText() {
    if (!selectedPhoto || !selectedPhoto.is_rich_text) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await updateGalleryPhotoRichText(selectedPhoto.id, richTextDraft);
      setSelectedPhoto(detail);
      await refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存图文文本失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleSaveLightboxRichText() {
    if (!lightboxPhoto || !lightboxPhoto.is_rich_text) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await updateGalleryPhotoRichText(lightboxPhoto.id, lightboxRichTextDraft);
      setGalleryPhotos((current) =>
        current.map((photo) => (photo.id === detail.id ? { ...photo, rich_text: detail.rich_text } : photo))
      );
      if (selectedPhoto?.id === detail.id) {
        setSelectedPhoto(detail);
        setRichTextDraft(detail.rich_text || "");
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "保存图文文本失败。");
    } finally {
      setBusy(false);
    }
  }

  function toggleGallerySelectionMode() {
    setGallerySelectionMode((current) => {
      if (current) {
        setSelectedGalleryPhotoIds([]);
      }
      return !current;
    });
  }

  async function handleDeleteSelectedGalleryPhotos() {
    if (selectedGalleryPhotoIds.length === 0) {
      return;
    }
    if (!await confirm({ title: "删除图库图片", message: `确认删除选中的 ${selectedGalleryPhotoIds.length} 张图库图片吗？这会删除图片文件、识别记录和向量数据。`, confirmLabel: "删除", tone: "danger" })) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeleteGalleryPhotos(selectedGalleryPhotoIds);
      if (selectedPhoto && selectedGalleryPhotoIds.includes(selectedPhoto.id)) {
        setSelectedPhoto(null);
      }
      setSelectedGalleryPhotoIds([]);
      setGallerySelectionMode(false);
      await refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量删除图库图片失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleDeleteCurrentPhoto() {
    if (!selectedPhoto) {
      return;
    }
    if (!await confirm({ title: "删除图库图片", message: `确认删除当前图片（ID: ${selectedPhoto.id}）吗？`, confirmLabel: "删除", tone: "danger" })) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteGalleryPhoto(selectedPhoto.id);
      setSelectedGalleryPhotoIds((current) => current.filter((id) => id !== selectedPhoto.id));
      setSelectedPhoto(null);
      await refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除图片失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleReRecognize() {
    if (!selectedPhoto) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await reRecognizeGalleryPhoto(selectedPhoto.id);
      setSelectedPhoto(detail);
      if (detail.recognition_summary) {
        const summary = detail.recognition_summary;
        setRecognitionNotice({
          id: Date.now(),
          message: `检测 ${summary.faces} 张脸，识别 ${summary.known} 张，未知 ${summary.unknown} 张，保留 ${summary.manual_tags_preserved} 个人工标签。`
        });
      }
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "重新识别失败。");
    } finally {
      setBusy(false);
    }
  }

  const totalPages = Math.ceil(galleryTotal / galleryPageSize);
  const currentPage = Math.floor(galleryOffset / galleryPageSize) + 1;

  function handleJumpToPage() {
    const pageNum = parseInt(jumpPageInput, 10);
    if (isNaN(pageNum) || pageNum < 1 || pageNum > totalPages) {
      setError(`请输入 1-${totalPages} 之间的页码`);
      return;
    }
    const newOffset = (pageNum - 1) * galleryPageSize;
    void refreshGallery(newOffset, selectedPersonIds, selectedTagIds);
    setJumpPageInput("");
  }

  const availablePersonsForPhoto = availablePhotoPersons(persons, selectedPhoto?.persons ?? []);
  const matchingPersonsForPhoto = filterPersonMatches(availablePersonsForPhoto, manualPersonSearch);

  const selectedPhotoTags = selectedPhoto ? sortByPinyinName(selectedPhoto.tags) : [];

  const availableTagsForPhoto = selectedPhoto
    ? sortByPinyinName(tags.filter((tag) => !tag.is_system && !selectedPhoto.tags.some((item) => item.id === tag.id)))
    : sortByPinyinName(tags.filter((tag) => !tag.is_system));

  const matchingTagsForPhoto = filterTagMatches(availableTagsForPhoto, manualTagSearch);

  const lightboxIndex = lightboxPhotoId === null ? -1 : galleryPhotos.findIndex((photo) => photo.id === lightboxPhotoId);
  const lightboxPhoto = lightboxIndex >= 0 ? galleryPhotos[lightboxIndex] : null;

  useEffect(() => {
    if (lightboxPhoto && lightboxPhoto.is_rich_text) {
      setLightboxRichTextDraft(lightboxPhoto.rich_text || "");
    }
  }, [lightboxPhoto]);
  const isFirstOfPage = lightboxIndex === 0;
  const isLastOfPage = lightboxIndex === galleryPhotos.length - 1;
  const hasPrevPage = galleryOffset > 0;
  const hasNextPage = galleryOffset + galleryPageSize < galleryTotal;

  const canGoPrev = lightboxIndex > 0 || hasPrevPage;
  const canGoNext = lightboxIndex >= 0 && (!isLastOfPage || hasNextPage);

  const lightboxMeta = lightboxPhoto ? (
    <>
      <div className="lightbox-meta-head">
        <span>#{lightboxPhoto.id}</span>
        <strong>{lightboxIndex >= 0 ? `${galleryOffset + lightboxIndex + 1} / ${galleryTotal}` : "图片信息"}</strong>
      </div>
      <div className="lightbox-meta-section">
        <span>人物标签</span>
        <div className="lightbox-meta-chips">
          {lightboxPhoto.persons.length > 0 ? (
            lightboxPhoto.persons.map((person) => (
              <small key={`rail-p-${lightboxPhoto.id}-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                {person.person_name}
              </small>
            ))
          ) : (
            <small className="lightbox-meta-empty">无人物标签</small>
          )}
        </div>
      </div>
      <div className="lightbox-meta-section">
        <span>普通标签</span>
        <div className="lightbox-meta-chips">
          {lightboxPhoto.tags.length > 0 ? (
            sortByPinyinName(lightboxPhoto.tags).map((tag) => (
              <small key={`rail-t-${lightboxPhoto.id}-${tag.id}`} className="pill muted">
                #{tag.name}
              </small>
            ))
          ) : (
            <small className="lightbox-meta-empty">无普通标签</small>
          )}
        </div>
      </div>
      <button className="lightbox-detail-button" disabled={busy} onClick={() => void openLightboxPhotoDetail()}>
        <Info size={16} aria-hidden="true" />
        查看详情
      </button>
    </>
  ) : null;

  async function goPrevLightbox() {
    if (lightboxIndex > 0) {
      setLightboxPhotoId(galleryPhotos[lightboxIndex - 1].id);
    } else if (hasPrevPage) {
      const newOffset = Math.max(0, galleryOffset - galleryPageSize);
      setBusy(true);
      try {
        const response = await listGalleryPhotos(selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds, newOffset, galleryPageSize);
        setGalleryPhotos(response.items);
        setGalleryTotal(response.total);
        setGalleryOffset(response.offset);
        setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
        if (response.items.length > 0) {
          setLightboxPhotoId(response.items[response.items.length - 1].id);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "翻页失败");
      } finally {
        setBusy(false);
      }
    }
  }

  async function goNextLightbox() {
    if (lightboxIndex >= 0 && lightboxIndex < galleryPhotos.length - 1) {
      setLightboxPhotoId(galleryPhotos[lightboxIndex + 1].id);
    } else if (hasNextPage) {
      const newOffset = galleryOffset + galleryPageSize;
      setBusy(true);
      try {
        const response = await listGalleryPhotos(selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds, newOffset, galleryPageSize);
        setGalleryPhotos(response.items);
        setGalleryTotal(response.total);
        setGalleryOffset(response.offset);
        setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
        if (response.items.length > 0) {
          setLightboxPhotoId(response.items[0].id);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "翻页失败");
      } finally {
        setBusy(false);
      }
    }
  }

  const GalleryPageComponent = () => {
    return (
        <main className="page-grid gallery-page">
          <section
            id="gallery-filter-drawer"
            ref={galleryFilterRef}
            className={`panel filter-panel gallery-drawer gallery-filter-drawer${galleryDrawer === "filter" ? " is-open" : ""}`}
            role={galleryCompact ? "dialog" : undefined}
            aria-modal={galleryCompact ? true : undefined}
            aria-hidden={galleryCompact ? galleryDrawer !== "filter" : undefined}
            aria-labelledby="gallery-filter-title"
            tabIndex={-1}
          >
            <div className="section-head">
              <div>
                <p className="eyebrow">筛选器</p>
                <h2 id="gallery-filter-title">人物 + 自定义标签</h2>
              </div>
              <div className="gallery-drawer-head-actions">
                <span>组内 OR，组间 AND</span>
                <button
                  ref={galleryFilterCloseRef}
                  className="gallery-drawer-close"
                  type="button"
                  onClick={() => closeGalleryDrawer()}
                  aria-label="关闭筛选器"
                  title="关闭筛选器"
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
            </div>

            <div className="filter-group">
              <label>按人物筛选</label>
              <input
                className="search-input subtle"
                value={personSearch}
                onChange={(event) => setPersonSearch(event.target.value)}
                placeholder="搜索人物名称、拼音或首字母"
              />
              <div className="filter-stack">
                {selectedFilterPersons.length > 0 && (
                  <div className="filter-section selected-filter-section">
                    <div className="filter-section-head">
                      <strong>已选人物</strong>
                      <span>
                        {selectedFilterPersons.length} 个{selectedUnknownPersonCount > 0 ? ` · 未知 ${selectedUnknownPersonCount}` : ""}
                      </span>
                    </div>
                    <div className="chip-cloud compact scroll-cloud selected-cloud">
                      {selectedFilterPersons.map((person) => (
                        <button
                          key={person.id}
                          className={person.is_unknown ? "soft-chip active unknown-chip" : "soft-chip active"}
                          onClick={() => handleTogglePersonFilter(person.id)}
                        >
                          {person.display_name}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="filter-section">
                  <div className="filter-section-head">
                    <strong>正式人物</strong>
                    <span>{knownFilterPersons.length} 个</span>
                  </div>
                  <div className="chip-cloud compact scroll-cloud known-person-cloud">
                    {knownFilterPersons.map((person) => (
                      <button
                        key={person.id}
                        className="soft-chip"
                        onClick={() => handleTogglePersonFilter(person.id)}
                      >
                        {person.display_name}
                      </button>
                    ))}
                    {knownFilterPersons.length === 0 && <span className="filter-empty">没有匹配的正式人物</span>}
                  </div>
                </div>

                <div className="filter-section">
                  <div className="filter-section-toolbar">
                    <button
                      className="filter-section-toggle"
                      onClick={() => setShowUnknownPersons((current) => !current)}
                      type="button"
                    >
                      <span>未知人物</span>
                      <small>
                        {personSearchActive ? `${allFilteredUnknownPersons.length} / ${unknownPersonCount}` : `${unknownPersonCount} 个`}
                      </small>
                      <b>{showUnknownPersons || personSearchActive ? "收起" : "展开"}</b>
                    </button>
                    <button
                      className="filter-bulk-action"
                      disabled={allFilteredUnknownPersons.length === 0}
                      onClick={handleToggleUnknownPersonFilters}
                      type="button"
                    >
                      {allFilteredUnknownSelected ? "全不选" : "全选"}
                    </button>
                  </div>
                  {(showUnknownPersons || personSearchActive) && (
                    <div className="chip-cloud compact scroll-cloud unknown-person-cloud">
                      {visibleUnknownFilterPersons.map((person) => (
                        <button
                          key={person.id}
                          className="soft-chip unknown-chip"
                          onClick={() => handleTogglePersonFilter(person.id)}
                        >
                          {person.display_name}
                        </button>
                      ))}
                      {visibleUnknownFilterPersons.length === 0 && <span className="filter-empty">没有匹配的未知人物</span>}
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="filter-group">
              <label>按普通标签筛选</label>
              <input
                className="search-input subtle"
                value={tagSearch}
                onChange={(event) => setTagSearch(event.target.value)}
                placeholder="搜索标签"
              />
              <div className="chip-cloud compact scroll-cloud tag-filter-cloud">
                {filteredTags.map((tag) => {
                  const active = selectedTagIds.includes(tag.id);
                  const inExclude = excludeTagIds.includes(tag.id);
                  return (
                    <button
                      key={tag.id}
                      className={active ? "soft-chip active" : "soft-chip"}
                      onClick={() => {
                        const next = active ? selectedTagIds.filter((id) => id !== tag.id) : [...selectedTagIds, tag.id];
                        setSelectedTagIds(next);
                        let nextExclude = excludeTagIds;
                        if (!active && excludeTagIds.includes(tag.id)) {
                          nextExclude = excludeTagIds.filter((id) => id !== tag.id);
                          setExcludeTagIds(nextExclude);
                        }
                        void refreshGallery(0, selectedPersonIds, next, excludePersonIds, nextExclude);
                      }}
                    >
                      #{tag.name}
                    </button>
                  );
                })}
                {filteredTags.length === 0 && <span className="filter-empty">没有匹配的普通标签</span>}
              </div>
            </div>

            <div className="filter-group">
              <label>排除筛选 · 不含所选条件的图片</label>

              <div className="filter-section">
                <div className="filter-section-toolbar">
                  <button
                    className="filter-section-toggle"
                    onClick={() => setShowExcludePersons((current) => !current)}
                    type="button"
                  >
                    <span>排除的人物</span>
                    <small>{excludedFilterPersons.length > 0 ? `${excludedFilterPersons.length} 个已选` : `${availableExcludePersons.length} 个可选`}</small>
                    <b>{showExcludePersons ? "收起" : "展开"}</b>
                  </button>
                </div>
                {showExcludePersons && (
                  <>
                    {excludedFilterPersons.length > 0 && (
                      <div className="filter-section selected-filter-section">
                        <div className="filter-section-head">
                          <strong>已选排除</strong>
                          <span>{excludedFilterPersons.length} 个</span>
                        </div>
                        <div className="chip-cloud compact scroll-cloud selected-cloud">
                          {excludedFilterPersons.map((person) => (
                            <button
                              key={person.id}
                              className={person.is_unknown ? "soft-chip active unknown-chip" : "soft-chip active"}
                              onClick={() => handleToggleExcludePerson(person.id)}
                            >
                              {person.display_name} ✕
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="filter-section">
                      <div className="filter-section-head">
                        <strong>正式人物</strong>
                        <span>{availableExcludeKnownPersons.length} 个</span>
                      </div>
                      <div className="chip-cloud compact scroll-cloud known-person-cloud">
                        {availableExcludeKnownPersons.map((person) => (
                          <button
                            key={person.id}
                            className="soft-chip"
                            onClick={() => handleToggleExcludePerson(person.id)}
                          >
                            {person.display_name}
                          </button>
                        ))}
                        {availableExcludeKnownPersons.length === 0 && <span className="filter-empty">没有可选人物</span>}
                      </div>
                    </div>
                    <div className="filter-section">
                      <div className="filter-section-head">
                        <strong>未知人物</strong>
                        <span>{availableExcludeUnknownPersons.length} 个</span>
                      </div>
                      <div className="chip-cloud compact scroll-cloud unknown-person-cloud">
                        {availableExcludeUnknownPersons.map((person) => (
                          <button
                            key={person.id}
                            className="soft-chip"
                            onClick={() => handleToggleExcludePerson(person.id)}
                          >
                            {person.display_name}
                          </button>
                        ))}
                        {availableExcludeUnknownPersons.length === 0 && <span className="filter-empty">没有可选人物</span>}
                      </div>
                    </div>
                  </>
                )}
              </div>

              <div className="filter-section">
                <div className="filter-section-toolbar">
                  <button
                    className="filter-section-toggle"
                    onClick={() => setShowExcludeTags((current) => !current)}
                    type="button"
                  >
                    <span>排除的标签</span>
                    <small>{excludedFilterTags.length > 0 ? `${excludedFilterTags.length} 个已选` : `${availableExcludeTags.length} 个可选`}</small>
                    <b>{showExcludeTags ? "收起" : "展开"}</b>
                  </button>
                </div>
                {showExcludeTags && (
                  <>
                    {excludedFilterTags.length > 0 && (
                      <div className="filter-section selected-filter-section">
                        <div className="filter-section-head">
                          <strong>已选排除</strong>
                          <span>{excludedFilterTags.length} 个</span>
                        </div>
                        <div className="chip-cloud compact scroll-cloud selected-cloud">
                          {excludedFilterTags.map((tag) => (
                            <button
                              key={tag.id}
                              className="soft-chip active"
                              onClick={() => handleToggleExcludeTag(tag.id)}
                            >
                              #{tag.name}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    <div className="chip-cloud compact scroll-cloud tag-filter-cloud">
                      {availableExcludeTags.map((tag) => (
                        <button
                          key={tag.id}
                          className="soft-chip"
                          onClick={() => handleToggleExcludeTag(tag.id)}
                        >
                          #{tag.name}
                        </button>
                      ))}
                      {availableExcludeTags.length === 0 && <span className="filter-empty">没有可选标签</span>}
                    </div>
                  </>
                )}
              </div>
            </div>
          </section>

          <section className="panel gallery-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">展示图库</p>
                <h2>按条件浏览图片</h2>
              </div>
              <div className="micro-row section-actions">
                <button
                  ref={galleryFilterTriggerRef}
                  className="gallery-drawer-trigger"
                  type="button"
                  onClick={() => openGalleryDrawer("filter")}
                  aria-controls="gallery-filter-drawer"
                  aria-expanded={galleryDrawer === "filter"}
                >
                  <SlidersHorizontal size={17} aria-hidden="true" />
                  筛选
                  {galleryFilterCount > 0 && <strong className="gallery-filter-count">{galleryFilterCount}</strong>}
                </button>
                <span>{galleryTotal} 张结果</span>
                <button disabled={busy} onClick={() => toggleGallerySelectionMode()}>
                  {gallerySelectionMode ? "取消选择" : "选择图片"}
                </button>
                <button disabled={busy} onClick={openGalleryExportModal}>
                  导出展示图
                </button>
                <button disabled={busy} onClick={handlePickGalleryImportFile}>
                  导入展示图
                </button>
                <button
                  disabled={busy || !gallerySelectionMode || selectedGalleryPhotoIds.length === 0}
                  onClick={() => void handleDeleteSelectedGalleryPhotos()}
                >
                  删除选中（{selectedGalleryPhotoIds.length}）
                </button>
                <input
                  ref={galleryImportFileRef}
                  type="file"
                  accept=".zip"
                  style={{ display: "none" }}
                  onChange={(event) => void handleGalleryImportFileChange(event)}
                />
                {galleryImportTask && galleryImportTask.status !== "completed" && galleryImportTask.status !== "failed" && (
                  <div className="task-bar gallery-task">
                    <progress value={galleryImportTask.progress} max={1}></progress>
                    <span>{galleryImportTask.message}</span>
                  </div>
                )}
                {galleryImportTask && galleryImportTask.status === "completed" && (
                  <div className="task-bar success gallery-task">
                    <span>{galleryImportTask.message}</span>
                  </div>
                )}
                {galleryImportTask && galleryImportTask.status === "failed" && (
                  <div className="task-bar error gallery-task">
                    <span>导入失败：{galleryImportTask.message}</span>
                  </div>
                )}
              </div>
            </div>

            <div className="gallery-grid">
              {galleryPhotos.map((photo) => {
                const isLandscape = photo.width && photo.height && photo.width / photo.height > 1.15;
                const wrapClass = photo.is_rich_text
                  ? "photo-card-wrap rich-card-wrap"
                  : `photo-card-wrap ${isLandscape ? "span-2" : ""}`;

                return (
                  <article key={photo.id} className={wrapClass}>
                    <button className={photo.is_rich_text ? "photo-card rich-card" : "photo-card"} onClick={() => openGalleryLightbox(photo.id)}>
                    {photo.is_rich_text ? (
                      <div className="rich-card-layout">
                        <img src={photo.animated_thumbnail_url} alt="图库预览" loading="lazy" />
                        <div className="rich-card-copy">
                          <p className="rich-snippet">{photo.rich_text || "未识别到文本，可在详情里手动补录。"}</p>
                          <div className="micro-row">
                            {photo.persons.map((person) => (
                              <small key={`${photo.id}-p-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                                {person.person_name}
                              </small>
                            ))}
                          </div>
                          <div className="micro-row">
                            {sortByPinyinName(photo.tags).map((tag) => (
                              <small key={`${photo.id}-t-${tag.id}`} className="pill muted">
                                #{tag.name}
                              </small>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : (
                      <>
                        <img src={photo.animated_thumbnail_url} alt="图库预览" loading="lazy" />
                        <div className="photo-meta">
                          <div className="micro-row">
                            {photo.persons.map((person) => (
                              <small key={`${photo.id}-p-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                                {person.person_name}
                              </small>
                            ))}
                          </div>
                          <div className="micro-row">
                            {sortByPinyinName(photo.tags).map((tag) => (
                              <small key={`${photo.id}-t-${tag.id}`} className="pill muted">
                                #{tag.name}
                              </small>
                            ))}
                          </div>
                        </div>
                      </>
                    )}
                  </button>
                  <button
                    className="photo-detail-trigger"
                    onClick={(event) => {
                      event.stopPropagation();
                      void openGalleryPhoto(photo.id);
                    }}
                  >
                    详情
                  </button>
                  {gallerySelectionMode && (
                    <label className="corner-check">
                      <input
                        type="checkbox"
                        checked={selectedGalleryPhotoIds.includes(photo.id)}
                        onChange={(event) => {
                          setSelectedGalleryPhotoIds((current) =>
                            event.target.checked ? [...current, photo.id] : current.filter((id) => id !== photo.id)
                          );
                        }}
                      />
                    </label>
                  )}
                </article>
              );
            })}
              {galleryPhotos.length === 0 && <div className="empty-card">当前筛选条件下没有展示图。</div>}
            </div>

            <div className="pagination-row">
              <button disabled={galleryOffset === 0 || busy} onClick={() => void refreshGallery(Math.max(0, galleryOffset - galleryPageSize))}>
                上一页
              </button>
              <span>
                第 {currentPage} / {totalPages} 页 ({galleryTotal === 0 ? 0 : galleryOffset + 1} - {Math.min(galleryOffset + galleryPageSize, galleryTotal)} / {galleryTotal})
              </span>
              <button
                disabled={galleryOffset + galleryPageSize >= galleryTotal || busy}
                onClick={() => void refreshGallery(galleryOffset + galleryPageSize)}
              >
                下一页
              </button>
              <div className="jump-to-page">
                <input
                  type="number"
                  min={1}
                  max={totalPages}
                  value={jumpPageInput}
                  onChange={(e) => setJumpPageInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      handleJumpToPage();
                    }
                  }}
                  placeholder="页码"
                />
                <button disabled={busy || !jumpPageInput} onClick={() => handleJumpToPage()}>
                  跳转
                </button>
              </div>
            </div>
          </section>

          <aside
            id="gallery-detail-drawer"
            ref={galleryDetailRef}
            className={`panel detail-panel gallery-drawer gallery-detail-drawer${galleryDrawer === "detail" ? " is-open" : ""}`}
            role={galleryCompact ? "dialog" : undefined}
            aria-modal={galleryCompact ? true : undefined}
            aria-hidden={galleryCompact ? galleryDrawer !== "detail" : undefined}
            aria-labelledby="gallery-detail-title"
            tabIndex={-1}
          >
            <div className="section-head">
              <div>
                <p className="eyebrow">详情</p>
                <h2 id="gallery-detail-title">单张图修正</h2>
              </div>
              <div className="micro-row">
                <span>{selectedPhoto ? `${selectedPhoto.faces.length} 张脸` : "未选中图片"}</span>
                <button disabled={busy || !selectedPhoto} onClick={() => void handleReRecognize()}>
                  重新识别
                </button>
                <button disabled={busy || !selectedPhoto} onClick={() => void handleDeleteCurrentPhoto()}>
                  删除当前图
                </button>
                <button
                  ref={galleryDetailCloseRef}
                  className="gallery-drawer-close"
                  type="button"
                  onClick={() => closeGalleryDrawer()}
                  aria-label="关闭图片详情"
                  title="关闭图片详情"
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
            </div>
            {selectedPhoto ? (
              <>
                <a className="detail-image-wrap" href={selectedPhoto.original_url} target="_blank" rel="noreferrer">
                  <img className="detail-image" src={selectedPhoto.original_url} alt="原图预览" />
                </a>
                <div className="detail-copy">
                  <h3>图片详情</h3>
                  <p>{formatPhotoDate(selectedPhoto.taken_at, selectedPhoto.created_at)}</p>
                  <p>
                    {selectedPhoto.width} × {selectedPhoto.height}
                  </p>
                </div>

                <div className="editor-block">
                  <label>人物标签</label>
                  <div className="micro-row wrap">
                    {selectedPhoto.persons.map((person) => (
                      <span key={person.person_id} className="micro-row">
                        <button
                          className={person.is_unknown ? "pill unknown action-pill" : "pill action-pill"}
                          onClick={() => void handleDeletePhotoPerson(person.person_id)}
                          title="移除此人物标签"
                        >
                          {person.person_name}
                        </button>
                        {!person.is_unknown && person.promoted_sample_id === null && (
                          <button
                            className="ghost-button"
                            disabled={busy || selectedPhoto.faces.length !== 1}
                            onClick={() => void handlePromotePhotoPerson(person.person_id)}
                          >
                            加入样本库
                          </button>
                        )}
                        {!person.is_unknown && person.promoted_sample_id !== null && (
                          <>
                            <button className="ghost-button" disabled>已加入样本库</button>
                            <button
                              className="ghost-button"
                              disabled={busy}
                              onClick={() => void handleUndoPromotePhotoPerson(person.person_id)}
                            >
                              撤销
                            </button>
                          </>
                        )}
                      </span>
                    ))}
                  </div>
                  <div className="searchable-picker-row">
                    <SearchableSelect
                      id="photo-person-picker"
                      value={manualPersonId}
                      query={manualPersonSearch}
                      options={matchingPersonsForPhoto.map((person) => ({
                        value: String(person.id),
                        label: person.display_name,
                        meta: `${person.gallery_photo_count} 张图库图片`
                      }))}
                      placeholder="搜索人物名称、拼音或首字母"
                      emptyText="没有匹配的人物"
                      disabled={busy}
                      onQueryChange={(query) => {
                        setManualPersonSearch(query);
                        setManualPersonId("");
                        setManualPersonNotice(null);
                      }}
                      onSelect={(option) => {
                        setManualPersonId(option.value);
                        setManualPersonSearch(option.label);
                        setManualPersonNotice(null);
                      }}
                      onEnter={() => void handleAddPhotoPerson()}
                    />
                    <button disabled={busy || !manualPersonSearch.trim()} onClick={() => void handleAddPhotoPerson()}>添加人物</button>
                  </div>
                  {manualPersonNotice && <p className="searchable-picker-notice" role="alert">{manualPersonNotice}</p>}
                  <p className="tip">
                    添加人物只修正当前图片标签；标签添加后，可在人物名称旁单独加入样本库或撤销。
                  </p>
                </div>

                <div className="editor-block">
                  <label>普通标签</label>
                  <div className="micro-row wrap">
                    {selectedPhotoTags.map((tag) => (
                      tag.is_system ? (
                        <span key={tag.id} className="pill muted">
                          #{tag.name}
                        </span>
                      ) : (
                        <button key={tag.id} className="pill muted action-pill" onClick={() => void handleDeletePhotoTag(tag.id)}>
                          #{tag.name}
                        </button>
                      )
                    ))}
                  </div>
                  <div className="stack-editor">
                    <div className="searchable-picker-row">
                      <SearchableSelect
                        id="photo-tag-picker"
                        value={manualTagId}
                        query={manualTagSearch}
                        options={matchingTagsForPhoto.map((tag) => ({
                          value: String(tag.id),
                          label: `#${tag.name}`
                        }))}
                        placeholder="搜索已有标签"
                        emptyText="没有匹配的已有标签"
                        disabled={busy}
                        onQueryChange={(query) => {
                          setManualTagSearch(query.replace(/^#/, ""));
                          setManualTagId("");
                          setManualTagNotice(null);
                        }}
                        onSelect={(option) => {
                          const tag = availableTagsForPhoto.find((item) => String(item.id) === option.value);
                          setManualTagId(option.value);
                          setManualTagSearch(tag?.name ?? option.label.replace(/^#/, ""));
                          setManualTagNotice(null);
                        }}
                        onEnter={() => void handleAddExistingPhotoTag()}
                      />
                      <button disabled={busy || !manualTagSearch.trim()} onClick={() => void handleAddExistingPhotoTag()}>
                        添加已有标签
                      </button>
                    </div>
                    {manualTagNotice && <p className="searchable-picker-notice" role="alert">{manualTagNotice}</p>}
                    <div className="inline-editor">
                      <input
                        value={manualTagName}
                        onChange={(event) => setManualTagName(event.target.value)}
                        placeholder="输入新标签名称"
                      />
                      <button disabled={busy || !manualTagName.trim()} onClick={() => void handleCreateAndAddPhotoTag()}>
                        新建并添加
                      </button>
                    </div>
                  </div>
                </div>

                {selectedPhoto.is_rich_text && (
                  <div className="editor-block">
                    <label>图文文本（可手动编辑）</label>
                    <textarea
                      className="rich-text-editor"
                      value={richTextDraft}
                      onChange={(event) => setRichTextDraft(event.target.value)}
                      placeholder="输入或修正文案内容"
                    />
                    <div className="micro-row">
                      <span>OCR状态：{selectedPhoto.ocr_status ?? "unknown"}</span>
                      <button disabled={busy} onClick={() => void handleSaveRichText()}>
                        保存图文文本
                      </button>
                    </div>
                  </div>
                )}

                <div className="face-list">
                  {selectedPhoto.faces.map((face) => (
                    <article key={face.id}>
                      <strong>Face #{face.id}</strong>
                      <span>{face.needs_review ? "待人工确认" : "已确认"}</span>
                      <span>
                        {face.predicted_person_id !== null && face.match_score !== null
                          ? `第一候选 ${face.predicted_person_name ?? `#${face.predicted_person_id}`}（#${face.predicted_person_id}），score ${face.match_score.toFixed(3)}`
                          : "无第一候选"}
                      </span>
                      {face.second_person_id !== null && face.second_match_score !== null && (
                        <span>
                          第二候选 {face.second_person_name ?? `#${face.second_person_id}`}（#{face.second_person_id}），score {face.second_match_score.toFixed(3)}
                        </span>
                      )}
                      {face.match_margin !== null && <span>候选差值 {face.match_margin.toFixed(3)}</span>}
                      {face.rejection_reason && (
                        <span>
                          拒绝原因：
                          {{
                            no_candidate: "没有候选人物",
                            candidate_not_found: "候选人物不存在",
                            below_threshold: "第一候选低于阈值",
                            insufficient_margin: "前两名差值不足",
                          }[face.rejection_reason] ?? face.rejection_reason}
                        </span>
                      )}
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-card">从图库卡片打开详情后，这里会显示识别结果和修正操作。</div>
            )}
          </aside>
          {galleryCompact && galleryDrawer && (
            <button
              className="gallery-drawer-backdrop"
              type="button"
              onClick={() => closeGalleryDrawer()}
              aria-label="关闭图库侧栏"
            />
          )}
        </main>
    );
  };

  const PeoplePageComponent = () => {
    return (
        <main className="page-grid people-page">
          <section className="panel people-sidebar">
            <div className="section-head">
              <div>
                <p className="eyebrow">人物库</p>
                <h2>创建与选择人物</h2>
              </div>
              <div className="people-count-badge">
                <span>{persons.length} 人</span>
              </div>
            </div>

            <div className="people-commandbar">
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy} onClick={() => togglePeopleBatchDeleteMode()}>
                  <Trash2 size={15} aria-hidden="true" />
                  {peopleBatchDeleteMode ? "取消批量" : "批量删除"}
                </button>
                <button
                  disabled={busy || !peopleBatchDeleteMode || selectedPersonDeleteCount === 0}
                  onClick={() => void handleDeleteSelectedPersons()}
                >
                  <Trash2 size={15} aria-hidden="true" />
                  删除选中（{selectedPersonDeleteCount}）
                </button>
              </div>
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleReRecognizeAllUnknownPhotos()}>
                  <RotateCcw size={15} aria-hidden="true" />
                  一键重新识别所有未知人物
                </button>
              </div>
              <div className="micro-row section-actions people-command-row">
                <button disabled={busy} onClick={handleExportPersons}>
                  <Download size={15} aria-hidden="true" />
                  导出样本库
                </button>
                <button disabled={busy} onClick={handlePickImportFile}>
                  <FileUp size={15} aria-hidden="true" />
                  导入样本库
                </button>
              </div>
                <input
                  ref={importFileRef}
                  type="file"
                  accept=".zip"
                  style={{ display: "none" }}
                  onChange={(event) => void handleImportFileChange(event)}
                />
                {importTask && importTask.status !== "completed" && importTask.status !== "failed" && (
                  <div className="task-bar">
                    <progress value={importTask.progress} max={1}></progress>
                    <span>{importTask.message}</span>
                  </div>
                )}
                {importTask && importTask.status === "completed" && (
                  <div className="task-bar success">
                    <span>{importTask.message}</span>
                  </div>
                )}
                {importTask && importTask.status === "failed" && (
                  <div className="task-bar error">
                    <span>导入失败：{importTask.message}</span>
                  </div>
                )}
            </div>

            <div className="inline-editor people-create-row">
              <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} placeholder="输入新人物名称" />
              <button disabled={busy || !newPersonName.trim()} onClick={() => void handleCreatePerson()}>
                <UserPlus size={15} aria-hidden="true" />
                创建人物
              </button>
            </div>

            <label className="people-search">
              <Search size={16} aria-hidden="true" />
              <input
                className="search-input subtle"
                value={peopleSearch}
                onChange={(event) => setPeopleSearch(event.target.value)}
                placeholder="搜索人物名称、拼音或首字母"
              />
            </label>

            <div className="person-list">
              {filteredPeopleInLibrary.map((person) => (
                <article key={person.id} className="person-card-wrap">
                  <button
                    className={selectedPerson?.id === person.id ? "person-card active" : "person-card"}
                    onClick={() => handleSelectPerson(person)}
                  >
                    <span className={person.is_unknown ? "person-avatar-marker unknown" : "person-avatar-marker"}>
                      {person.display_name.slice(0, 1)}
                    </span>
                    <div className="person-card-main">
                      <strong>{person.display_name}</strong>
                      <span>{person.is_unknown ? "未知人物" : "正式人物"}</span>
                    </div>
                    <small className="person-card-stats">
                      <b>{person.sample_count}</b>
                      <span>样本</span>
                      <b>{person.gallery_photo_count}</b>
                      <span>图库</span>
                    </small>
                  </button>
                  {peopleBatchDeleteMode && (
                    <label className="row-check">
                      <input
                        type="checkbox"
                        disabled={isSystemUnknownPerson(person)}
                        checked={selectedPersonDeleteIds.includes(person.id)}
                        onChange={(event) => {
                          if (isSystemUnknownPerson(person)) {
                            return;
                          }
                          setSelectedPersonDeleteIds((current) =>
                            event.target.checked ? [...current, person.id] : current.filter((id) => id !== person.id)
                          );
                        }}
                      />
                      <span>选中删除</span>
                    </label>
                  )}
                </article>
              ))}
              {filteredPeopleInLibrary.length === 0 && <div className="empty-card">没有匹配的人物。</div>}
            </div>
          </section>

          <section ref={peopleMainRef} className="panel people-main">
            {selectedPerson ? (
              <>
                <div className="section-head">
                  <div>
                    <p className="eyebrow">人物详情</p>
                    <h2>{selectedPerson.display_name}</h2>
                  </div>
                  <div className="micro-row">
                    <span>{selectedPersonIsSystemUnknown ? "图库未知标签" : selectedPerson.is_unknown ? "未知人物" : "样本库维护"}</span>
                    <button disabled={busy || selectedPersonIsSystemUnknown} onClick={() => void handleDeleteCurrentPerson()}>
                      删除当前人物
                    </button>
                  </div>
                </div>

                {!selectedPersonIsSystemUnknown && (
                  <>
                    <div className="rename-strip">
                      <input value={renameValue} onChange={(event) => setRenameValue(event.target.value)} placeholder="输入新名字" />
                      <button disabled={busy || !renameValue.trim()} onClick={() => void handleRenamePerson()}>
                        {selectedPerson.is_unknown ? "转正并改名" : "更新名称"}
                      </button>
                    </div>

                    <div className="editor-block">
                      <label>人物普通标签（自动继承到该人物相关图库图片）</label>
                      <div className="micro-row wrap">
                        {personTags.map((tag) => (
                          <button key={tag.id} className="pill muted action-pill" onClick={() => void handleUnbindPersonTag(tag.id)}>
                            #{tag.name}
                          </button>
                        ))}
                        {personTags.length === 0 && <span className="tip">还没有人物级普通标签。</span>}
                      </div>
                      <div className="stack-editor">
                        <div className="inline-editor">
                          <select value={personTagSelectId} onChange={(event) => setPersonTagSelectId(event.target.value)}>
                            <option value="">从已有标签添加</option>
                            {sortByPinyinName(tags.filter((tag) => !personTags.some((item) => item.id === tag.id))).map((tag) => (
                              <option key={tag.id} value={tag.id}>
                                #{tag.name}
                              </option>
                            ))}
                          </select>
                          <button disabled={busy || !personTagSelectId} onClick={() => void handleBindPersonTag()}>
                            添加已有标签
                          </button>
                        </div>
                        <div className="inline-editor">
                          <input
                            value={personTagName}
                            onChange={(event) => setPersonTagName(event.target.value)}
                            placeholder="输入新标签名称"
                          />
                          <button disabled={busy || !personTagName.trim()} onClick={() => void handleBindPersonTag()}>
                            新建并添加
                          </button>
                        </div>
                      </div>
                    </div>

                    <label className="upload-box">
                      <input type="file" multiple accept="image/*" onChange={(event) => handlePickSampleFiles(event.target.files)} />
                      <strong>上传人物样本图</strong>
                      <span>先预览样本，再点击确认上传；仅接受单张照片恰好一张脸的样本进入向量库。</span>
                    </label>
                  </>
                )}

                {!selectedPersonIsSystemUnknown && pendingSampleUploads.length > 0 && (
                  <div className="editor-block">
                    <label>待上传样本预览（{pendingSampleUploads.length}）</label>
                    <div className="pending-grid">
                      {pendingSampleUploads.map((item, index) => (
                        <article key={`${item.file.name}-${index}`} className="pending-card">
                          <img src={item.previewUrl} alt="样本预览" />
                          <div>
                            <strong>待上传样本 {index + 1}</strong>
                            <span>{Math.round(item.file.size / 1024)} KB</span>
                          </div>
                          <button className="ghost-button" onClick={() => handleRemovePendingSample(index)}>
                            移除
                          </button>
                        </article>
                      ))}
                    </div>
                    <button disabled={busy} onClick={() => void handleConfirmSampleUpload()}>
                      确认上传样本
                    </button>
                  </div>
                )}

                <div className="sample-grid">
                  {samples.map((sample) => {
                    const isLandscape = sample.width && sample.height && sample.width / sample.height > 1.15;
                    const cardClass = `sample-card ${isLandscape ? "span-2" : ""}`;

                    return (
                      <article key={sample.id} className={cardClass}>
                        <a href={sample.original_url} target="_blank" rel="noreferrer">
                          <img src={withImageWidth(sample.thumbnail_url, 480)} alt="样本缩略图" />
                        </a>
                        <div className="sample-copy">
                          <strong>样本记录 #{sample.id}</strong>
                          <span>{formatPhotoDate(sample.taken_at, sample.created_at)}</span>
                          <small className={`status-pill status-${sample.status}`}>{sample.status}</small>
                          {sample.error_message && <p>{sample.error_message}</p>}
                          {sample.source_type === "gallery_face" && (
                            sample.source_gallery_photo_id !== null ? (
                              <button
                                className="ghost-button"
                                onClick={() => void handleOpenSampleSource(sample.source_gallery_photo_id!)}
                              >
                                来源：展示图库 #{sample.source_gallery_photo_id}
                              </button>
                            ) : (
                              <small>来源展示图已删除</small>
                            )
                          )}
                        </div>
                        {!selectedPersonIsSystemUnknown && (
                          <button className="ghost-button" onClick={() => void handleDeleteSample(sample.id)}>
                            删除样本
                          </button>
                        )}
                      </article>
                    );
                  })}
                  {samples.length === 0 && <div className="empty-card">当前人物还没有样本图片。</div>}
                </div>
              </>
            ) : (
              <div className="empty-card">左侧选择一个人物后，在这里维护样本图。</div>
            )}
          </section>
        </main>
    );
  };

  const renderUploadPage = () => {
    const queueTotal = videoUploadQueue.length;
    const queueCompleted = videoUploadQueue.filter((item) => item.status === "completed").length;
    const queueFailed = videoUploadQueue.filter((item) => item.status === "failed").length;
    const queueNeedsFile = videoUploadQueue.filter((item) => item.status === "needs_file").length;
    const queueUploading = videoUploadQueue.find((item) => item.status === "uploading");
    const queueProgress =
      queueTotal > 0
        ? Math.round(videoUploadQueue.reduce((sum, item) => sum + item.progress, 0) / queueTotal)
        : videoUploadProgress;
    let videoUploadState = "待选择";
    if (queueTotal > 0) {
      videoUploadState =
        videoUploadBusy && videoUploadTotalCount > 0
          ? `上传中 ${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / ${videoUploadTotalCount}`
          : `队列 ${queueTotal} 个，完成 ${queueCompleted} 个`;
    } else if (videoUploadTotalCount > 0) {
      videoUploadState = `上传中 ${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / ${videoUploadTotalCount}`;
    } else if (videoFiles.length > 0) {
      videoUploadState = `已选择 ${videoFiles.length} 个视频`;
    }
    let videoUploadNote = "支持长视频分片上传，上传后自动转为网页可播放格式。";
    if (queueNeedsFile > 0) {
      videoUploadNote = `${queueNeedsFile} 个视频需要重新选择原文件后继续上传。`;
    } else if (queueFailed > 0) {
      videoUploadNote = `${queueFailed} 个视频上传失败，可重新选择原文件后继续。`;
    } else if (queueUploading) {
      videoUploadNote = queueUploading.filename;
    } else if (videoUploadQueue.length > 0) {
      videoUploadNote = videoUploadQueue.map((item) => item.filename).join("、");
    } else if (videoFiles.length > 0) {
      videoUploadNote = videoFiles.map((file) => file.name).join("、");
    }

    return (
        <main className="page-grid upload-page">
          <section className="panel upload-main">
            <div className="section-head">
              <div>
                <p className="eyebrow">素材上传</p>
                <h2>图片与视频统一入库</h2>
              </div>
              <span>批量导入工作台</span>
            </div>

            <div className="upload-channel-grid">
              <article className="upload-channel-card upload-channel-card-image">
                <div className="upload-channel-head">
                  <span className="upload-channel-icon">
                    <ImagePlus size={22} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="eyebrow">图片入库</p>
                    <h3>展示图识别</h3>
                  </div>
                </div>
                <div className="upload-mode-switch">
                  <button
                    className={uploadMode === "normal" ? "soft-chip active" : "soft-chip"}
                    onClick={() => setUploadMode("normal")}
                  >
                    普通图片
                  </button>
                  <button className={uploadMode === "rich" ? "soft-chip active" : "soft-chip"} onClick={() => setUploadMode("rich")}>
                    图文图片
                  </button>
                </div>
                <label className="upload-box large upload-box-image">
                  <input type="file" multiple accept="image/*" onChange={(event) => handlePickGalleryFiles(event.target.files)} />
                  <strong>{uploadMode === "rich" ? "选择图文图片" : "选择展示图片"}</strong>
                  <span>
                    {uploadMode === "rich"
                      ? "可补录文本或留空走 OCR，并自动执行人脸识别。"
                      : "预览后填写人物和标签，再统一提交到识别队列。"}
                  </span>
                </label>
                <small className="upload-channel-note">
                  {uploadMode === "rich"
                    ? `将自动打 #图文 标签${richTag ? "" : "（系统会自动创建）"}`
                    : "沿用普通图片流程：人脸识别 + 人物标签 + 普通标签"}
                </small>
              </article>

              <article className="upload-channel-card upload-channel-card-video">
                <div className="upload-channel-head">
                  <span className="upload-channel-icon">
                    <Clapperboard size={22} aria-hidden="true" />
                  </span>
                  <div>
                    <p className="eyebrow">视频入库</p>
                    <h3>分片上传</h3>
                  </div>
                </div>
                <div className="upload-channel-status">
                  <strong>{videoUploadState}</strong>
                  <span>{videoUploadNote}</span>
                </div>
                <div className="upload-channel-progress">
                  <div className="meter">
                    <span style={{ width: `${queueProgress}%` }} />
                  </div>
                  <small>{queueProgress}%</small>
                </div>
                <button className="primary upload-video-entry" onClick={() => setIsVideoUploadModalOpen(true)}>
                  <UploadCloud size={16} aria-hidden="true" />
                  上传视频
                </button>
              </article>
            </div>

            {pendingGalleryUploads.length > 0 && (
              <div className="editor-block">
                <div className="stack-editor">
                  <label>批量套用到全部待上传图片</label>
                  <div className="inline-editor">
                    <input
                      value={batchApplyPersonNames}
                      onChange={(event) => setBatchApplyPersonNames(event.target.value)}
                      placeholder="人物名字（逗号分隔）"
                    />
                    <input
                      value={batchApplyTagNames}
                      onChange={(event) => setBatchApplyTagNames(event.target.value)}
                      placeholder="普通标签（逗号分隔）"
                    />
                    <button disabled={galleryUploadBusy} onClick={() => handleApplyBatchMetadataToAll()}>
                      批量套用
                    </button>
                  </div>
                </div>
                <label>待上传图片（{pendingGalleryUploads.length}）</label>
                <div className="pending-grid pending-grid-gallery">
                  {pendingGalleryUploads.map((item, index) => (
                    <article key={`${item.file.name}-${index}`} className="pending-card pending-card-gallery">
                      <img src={item.previewUrl} alt="待上传预览" />
                      <div className="pending-card-copy">
                        <strong>待上传图片 {index + 1}</strong>
                        <span>{Math.round(item.file.size / 1024)} KB</span>
                        <input
                          value={item.personNamesText}
                          onChange={(event) => handleUpdatePendingGallery(index, { personNamesText: event.target.value })}
                          placeholder="人物名字（逗号分隔，可留空）"
                        />
                        <input
                          value={item.tagNamesText}
                          onChange={(event) => handleUpdatePendingGallery(index, { tagNamesText: event.target.value })}
                          placeholder="普通标签（逗号分隔，可留空）"
                        />
                        {uploadMode === "rich" && (
                          <textarea
                            className="rich-text-editor compact"
                            value={item.richText}
                            onChange={(event) => handleUpdatePendingGallery(index, { richText: event.target.value })}
                            placeholder="图文文本（可留空，后端自动OCR）"
                          />
                        )}
                      </div>
                      <button className="ghost-button" onClick={() => handleRemovePendingGallery(index)}>
                        移除
                      </button>
                    </article>
                  ))}
                </div>
                <button disabled={galleryUploadBusy} onClick={() => void handleConfirmGalleryUpload()}>
                  确认上传（批量）
                </button>
              </div>
            )}
          </section>

          <aside className="panel upload-side">
            <div className="section-head">
              <div>
                <p className="eyebrow">任务状态</p>
                <h2>识别进度</h2>
              </div>
            </div>

            <div className="task-box">
              <strong>{task ? task.status : "idle"}</strong>
              <p>{task?.message ?? "上传后会在这里看到导入进度和识别摘要。"}</p>
              <div className="meter">
                <span style={{ width: `${Math.round((task?.progress ?? 0) * 100)}%` }} />
              </div>
            </div>

            <div className="info-list">
              <article>
                <strong>已知人物</strong>
                <span>命中阈值后会直接写入展示图人物标签。</span>
              </article>
              <article>
                <strong>未知人物</strong>
                <span>未命中样本库时统一标记为“未知人物”，可在图库详情中重新识别或改为正式人物。</span>
              </article>
              <article>
                <strong>普通标签</strong>
                <span>支持选已有，也支持上传时现场新增，供展示图库组合检索。</span>
              </article>
            </div>

            <div className="info-list upload-video-info">
              <article>
                <strong>视频状态</strong>
                <span>{videoUploadState}</span>
              </article>
              <article>
                <strong>字幕处理</strong>
                <span>{videoUploadGenerateSubtitles ? "上传完成后自动提交中文字幕生成。" : "可在视频上传弹窗中开启中文字幕生成。"}</span>
              </article>
            </div>
          </aside>
        </main>
    );
  };

  const renderVideoUploadModal = () => {
    const selectedVideoFileIds = new Set(videoFiles.map((file) => videoFileFingerprint(file)));
    const uploadableQueueCount = videoUploadQueue.filter((item) => item.status !== "completed" && selectedVideoFileIds.has(item.id)).length;
    const queueNeedsFileCount = videoUploadQueue.filter((item) => item.status === "needs_file").length;
    const queueFailedCount = videoUploadQueue.filter((item) => item.status === "failed").length;
    const canStartVideoUpload = uploadableQueueCount > 0 && !(videoFiles.length === 1 && !videoTitle.trim());
    const videoModalProgress =
      videoUploadQueue.length > 0
        ? Math.round(videoUploadQueue.reduce((sum, item) => sum + item.progress, 0) / videoUploadQueue.length)
        : videoUploadProgress;

    return (
    <div className="modal-backdrop">
      <aside className="panel video-upload-panel bili-modal-content">
        <div className="section-head">
          <div>
            <p className="eyebrow">上传视频</p>
            <h2>分片入库</h2>
          </div>
          <button className="close-modal" onClick={() => setIsVideoUploadModalOpen(false)}>关闭</button>
        </div>

        <label className="upload-box video-upload-box">
          <input type="file" accept={supportedVideoAccept} multiple onChange={(event) => handlePickVideoFile(event.target.files)} />
          <strong>{videoFiles.length === 1 ? videoFiles[0].name : videoFiles.length > 1 ? `已选 ${videoFiles.length} 个视频` : `选择视频（${supportedVideoFormatLabel}，可多选）`}</strong>
          <span>{videoFiles.length >= 1 ? videoFiles.map((f) => formatBytes(f.size)).join("、") : "支持长视频分片上传，上传后会自动转为网页可播放格式。"}</span>
        </label>

        {videoUploadQueue.length > 0 && (
          <div className="editor-block">
            <label>
              上传队列（{videoUploadQueue.length}）
              {queueNeedsFileCount > 0 && ` · ${queueNeedsFileCount} 个需重选文件`}
              {queueFailedCount > 0 && ` · ${queueFailedCount} 个失败`}
            </label>
            <div className="video-upload-queue">
              {videoUploadQueue.map((item) => (
                <article key={item.id} className="video-upload-queue-item">
                  <div className="pending-card-copy">
                    <strong>{item.title || item.filename}</strong>
                    <span>{item.filename} · {formatBytes(item.size)}</span>
                    <span>{videoQueueStatusLabel(item.status)} · {item.progress}%</span>
                    <div className="meter">
                      <span style={{ width: `${item.progress}%` }} />
                    </div>
                    {item.error && <small>{item.error}</small>}
                  </div>
                </article>
              ))}
            </div>
          </div>
        )}

        <div className="stack-editor">
          <input value={videoTitle} onChange={(event) => setVideoTitle(event.target.value)} placeholder="单个视频时可自定义标题" disabled={videoFiles.length > 1} />
          <textarea
            className="rich-text-editor compact"
            value={videoDescription}
            onChange={(event) => setVideoDescription(event.target.value)}
            placeholder="视频简介（批量上传时所有文件共用此简介）"
          />
        </div>

        <div className="editor-block">
          <label>上传时绑定类别</label>
          <div className="chip-cloud compact">
            {videoCategoryTags.map((tag) => (
              <button
                key={tag.id}
                className={videoUploadCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                onClick={() => handleToggleVideoUploadCategory(tag.id)}
              >
                #{tag.name}
              </button>
            ))}
          </div>
          <input
            value={videoUploadNewCategories}
            onChange={(event) => setVideoUploadNewCategories(event.target.value)}
            placeholder="新类别标签，逗号分隔"
          />
        </div>

        <div className="editor-block">
          <label>上传时绑定人物</label>
          <div className="video-person-cloud compact">
            {videoPeople.map((person) => (
              <button
                key={person.id}
                className={videoUploadPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                onClick={() => handleToggleVideoUploadPerson(person.id)}
              >
                {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                <b>{person.name}</b>
              </button>
            ))}
          </div>
        </div>

        <label className="toggle-row subtitle-upload-toggle">
          <input
            type="checkbox"
            checked={videoUploadGenerateSubtitles}
            onChange={(event) => setVideoUploadGenerateSubtitles(event.target.checked)}
          />
          <span>自动生成中文字幕</span>
        </label>

        {error && <div className="error-banner modal-inline-error">{error}</div>}

        <div className="video-progress">
          <strong>{videoModalProgress}%</strong>
          <div className="meter"><span style={{ width: `${videoModalProgress}%` }} /></div>
          {videoUploadTotalCount > 0 && (
            <small>文件 {Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)} / {videoUploadTotalCount}</small>
          )}
          {videoUploadSession && <small>{videoUploadSession.uploaded_parts.length} / {videoUploadSession.total_parts} 分片</small>}
        </div>

        <div className="micro-row wrap">
          <button disabled={videoUploadBusy || !canStartVideoUpload} onClick={() => void handleConfirmVideoUpload()}>
            {videoUploadTotalCount > 0
              ? `上传中 (${Math.min(videoUploadCurrentIndex + 1, videoUploadTotalCount)}/${videoUploadTotalCount})`
              : videoUploadQueue.some((item) => item.status === "needs_file" || item.status === "failed")
                ? "继续上传"
                : "开始上传"}
          </button>
          <button className="ghost-button" disabled={videoUploadBusy} onClick={() => void handleCancelVideoUpload()}>
            清理续传会话
          </button>
        </div>
      </aside>
    </div>
  );
  };

  const renderVideosPage = () => {
    return (
        <main className="bili-videos-page">
          <div className="bili-top-bar">
            <div className="bili-search-box">
              <input
                className="search-input"
                value={videoSearch}
                onChange={(event) => setVideoSearch(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    void refreshVideos(0, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
                  }
                }}
                placeholder="搜索视频名、简介或文件名"
              />
              <button disabled={busy} onClick={() => void refreshVideos(0)}>
                搜索
              </button>
            </div>
            <div className="micro-row wrap compact-actions">
              <button className="compact-button" onClick={() => setIsCategoryManageModalOpen(true)}>管理分区</button>
              <button className="compact-button" onClick={() => setIsVideoPersonManageModalOpen(true)}>管理UP主</button>
            </div>
          </div>

          <section className="subtitle-service-panel">
            <div className="subtitle-service-head">
              <div>
                <p className="eyebrow">中文字幕</p>
                <h2>本地翻译服务</h2>
              </div>
              <div className="subtitle-service-actions">
                <span className={`subtitle-service-badge subtitle-service-badge-${subtitleServiceStatus?.status ?? "unknown"}`}>
                  {subtitleServiceStatus ? subtitleServiceStatusLabel(subtitleServiceStatus.status) : "检测中"}
                </span>
                <button disabled={subtitleServiceBusy} onClick={() => void handleStartSubtitleService()}>
                  启动服务
                </button>
                <button disabled={subtitleServiceBusy} onClick={() => void handleStopSubtitleService()}>
                  关闭服务
                </button>
                <button disabled={subtitleServiceBusy} onClick={() => void handleToggleSubtitleLogs()}>
                  {subtitleLogsOpen ? "收起日志" : "查看日志"}
                </button>
              </div>
            </div>

            <div className="subtitle-service-meta">
              <span>端点：{subtitleServiceStatus?.endpoint ?? "未检测"}</span>
              <span>PID：{subtitleServiceStatus?.pid ?? "无"}</span>
              <span>模型：{subtitleServiceStatus?.model ?? "Hy-MT2"}</span>
              <span>{subtitleServiceStatus?.managed ? "由 PictureShow 启动" : "外部或未启动"}</span>
            </div>

            <div className="subtitle-service-meta subtitle-service-asr-meta">
              <span>ASR：{subtitleServiceStatus?.asr ? subtitleAsrStatusLabel(subtitleServiceStatus.asr.status) : "检测中"}</span>
              <span>设备：{subtitleServiceStatus?.asr ? `${subtitleServiceStatus.asr.device}/${subtitleServiceStatus.asr.compute_type}` : "未检测"}</span>
              <span>模型：faster-whisper</span>
              {subtitleServiceStatus?.asr?.last_duration_seconds != null && (
                <span>上次耗时：{subtitleServiceStatus.asr.last_duration_seconds.toFixed(1)} 秒</span>
              )}
              {subtitleServiceStatus?.asr?.last_segment_count != null && (
                <span>上次片段：{subtitleServiceStatus.asr.last_segment_count}</span>
              )}
            </div>

            {(subtitleServiceNotice || subtitleServiceStatus?.message) && (
              <div
                className={
                  subtitleServiceNotice?.includes("失败") || subtitleServiceStatus?.status === "unhealthy"
                    ? "subtitle-service-message subtitle-service-message-error"
                    : "subtitle-service-message"
                }
              >
                {subtitleServiceNotice || subtitleServiceStatus?.message}
              </div>
            )}

            {subtitleServiceStatus?.asr?.message && (
              <div
                className={
                  subtitleServiceStatus.asr.status === "error"
                    ? "subtitle-service-message subtitle-service-message-error"
                    : "subtitle-service-message"
                }
              >
                语音识别：{subtitleServiceStatus.asr.message}
                {subtitleServiceStatus.asr.last_error ? `：${subtitleServiceStatus.asr.last_error}` : ""}
              </div>
            )}

            {visibleSubtitleJobs.length > 0 ? (
              <div className="subtitle-job-list">
                {visibleSubtitleJobs.map((job) => {
                  const progress = Math.round(Math.min(Math.max(job.task?.progress ?? 0, 0), 1) * 100);
                  const isActive = ["pending", "running"].includes(job.track.status);
                  return (
                    <div className={`subtitle-job-row subtitle-job-row-${job.track.status}`} key={`${job.video_id}-${job.track.id}`}>
                      <div className="subtitle-job-main">
                        <strong>{job.video_title}</strong>
                        <span>{subtitleTrackStatusLabel(job.track.status)} · {job.task?.message ?? job.video_filename}</span>
                        {job.track.error_message && <small>{job.track.error_message}</small>}
                      </div>
                      <div className="subtitle-job-progress">
                        <progress value={progress} max={100}></progress>
                        <span>{progress}%</span>
                      </div>
                      <button
                        className="ghost-button compact"
                        disabled={subtitleServiceBusy || !isActive}
                        onClick={() => void handleCancelSubtitleJob(job)}
                      >
                        取消
                      </button>
                    </div>
                  );
                })}
              </div>
            ) : !subtitleJobsLoaded ? (
              <p className="subtitle-service-empty">正在读取字幕任务...</p>
            ) : (
              <p className="subtitle-service-empty">当前没有字幕生成任务。</p>
            )}

            {subtitleLogsOpen && (
              <div className="subtitle-log-panel">
                <div className="subtitle-log-path">{subtitleServiceLogs?.log_path ?? "未配置日志文件"}</div>
                <pre>{subtitleServiceLogs?.content || "暂无日志"}</pre>
              </div>
            )}
          </section>

          <div className="bili-filters-bar">
            <div className="bili-filter-row">
              <span className="bili-filter-label">分区</span>
              <div className="bili-chip-cloud">
                <button
                  className={selectedVideoCategoryIds.length === 0 ? "soft-chip active" : "soft-chip"}
                  onClick={() => {
                    setSelectedVideoCategoryIds([]);
                    void refreshVideos(0, [], selectedVideoPersonIds, videoSearch);
                  }}
                >
                  全部
                </button>
                {filteredVideoCategoryTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={selectedVideoCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                    onClick={() => handleToggleVideoFilterCategory(tag.id)}
                  >
                    {tag.name}
                  </button>
                ))}
              </div>
            </div>

            <div className="bili-filter-row">
              <span className="bili-filter-label">UP主</span>
              <div className="bili-chip-cloud">
                <button
                  className={selectedVideoPersonIds.length === 0 ? "video-person-chip active" : "video-person-chip"}
                  onClick={() => {
                    setSelectedVideoPersonIds([]);
                    void refreshVideos(0, selectedVideoCategoryIds, [], videoSearch);
                  }}
                >
                  <b>全部</b>
                </button>
                {filteredVideoPeople.map((person) => (
                  <button
                    key={person.id}
                    className={selectedVideoPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                    onClick={() => handleToggleVideoFilterPerson(person.id)}
                  >
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                    <b>{person.name}</b>
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="bili-video-grid">
            {videoItems.map((video) => (
              <article
                key={video.id}
                className="bili-video-card"
                onClick={() => window.open("#video-play/" + video.id, "_blank")}
              >
                <div className="bili-video-cover">
                  {video.cover_url ? (
                    <img src={video.cover_url} alt={video.title} loading="lazy" />
                  ) : (
                    <span className="placeholder">{getVideoFormatLabel(video.filename)}</span>
                  )}
                  <span className={`bili-video-status status-${video.status}`}>{videoStatusLabel(video.status)}</span>
                  <span className="bili-video-duration">
                    {video.duration_seconds ? formatDurationSeconds(video.duration_seconds) : formatBytes(video.size_bytes)}
                  </span>
                </div>
                <div className="bili-video-info">
                  <h3 className="bili-video-title" title={video.title}>{video.title}</h3>
                  <div className="bili-up-list">
                    {video.people.map((person) => (
                      <div className="bili-up-item" key={person.id} title={person.name}>
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <span>{person.name}</span>
                      </div>
                    ))}
                    {video.people.length === 0 && <span className="muted small-muted">无UP主</span>}
                  </div>
                  <div className="bili-video-meta">
                    <span>{formatDate(video.created_at)}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {videoTotal > 0 && (
            <div className="pagination-row pagination-row-bottom">
              <button disabled={videoOffset === 0 || busy} onClick={() => void refreshVideos(Math.max(0, videoOffset - videoPageSize))}>
                上一页
              </button>
              <span>
                {videoOffset + 1} - {Math.min(videoOffset + videoPageSize, videoTotal)} / 共 {videoTotal}
              </span>
              <button disabled={videoOffset + videoPageSize >= videoTotal || busy} onClick={() => void refreshVideos(videoOffset + videoPageSize)}>
                下一页
              </button>
            </div>
          )}

        </main>
    );
  };

  const navItems = [
    { key: "home", label: "首页", Icon: HomeIcon },
    { key: "gallery", label: "展示图库", Icon: GalleryHorizontalEnd },
    { key: "similarity", label: "相似整理", Icon: ScanSearch },
    { key: "acquisition", label: "图片采集", Icon: FolderSync },
    { key: "people", label: "人物样本", Icon: UsersRound },
    { key: "upload", label: "上传", Icon: UploadCloud },
    { key: "videos", label: "视频库", Icon: Clapperboard },
    { key: "statistics", label: "统计", Icon: BarChart3 }
  ] as const;

  return (
    <div className="app-shell">
      <div className="sunwash sunwash-a" />
      <div className="sunwash sunwash-b" />

      <header className="topbar">
        <div>
          <p className="eyebrow">Local Face Archive</p>
          <h1>PictureShow</h1>
          <div className="session-strip">
            <button type="button" onClick={() => setWorkspacePanelOpen(true)}>
              <Settings size={14} aria-hidden="true" />
              {authSession.workspace.name}
            </button>
            <span>{authSession.user.display_name || authSession.user.username}</span>
            <span>{authSession.workspace.kind === "private" ? "私人空间" : authSession.workspace.role === "owner" ? "共享 owner" : "共享成员"}</span>
            <button type="button" onClick={onLogout}>
              <LogOut size={14} aria-hidden="true" />
              退出登录
            </button>
          </div>
        </div>
        <nav className="nav-tabs">
          {navItems.map(({ key, label, Icon }) => (
            <button
              key={key}
              className={page === key ? "nav-tab active" : "nav-tab"}
              onClick={() => {
                setPageState(key as PageKey);
                setRoute(key as PageKey);
              }}
            >
              <Icon size={16} aria-hidden="true" />
              {label}
            </button>
          ))}
        </nav>
      </header>

      {workspacePanelOpen && (
        <WorkspacePanel
          session={authSession}
          onSessionChange={onSessionChange}
          onClose={() => setWorkspacePanelOpen(false)}
        />
      )}

      {page === "statistics" && <Statistics />}

      {page === "videos" && renderVideosPage()}

      {page === "video-play" && (
        <main className="video-play-page">
          <section className="video-play-main">
            {selectedVideo ? (
              <div className="panel video-player-panel">
                {(() => {
                  const subtitleTracks = selectedVideo.subtitle_tracks
                    .filter((track) => track.status === "ready" && track.vtt_url)
                    .map((track) => ({
                      src: track.vtt_url as string,
                      label: track.label,
                      srclang: track.language
                    }));
                  return (
                    <BiliVideoPlayer
                      src={videoPlayerUrl}
                      poster={selectedVideo.cover_url ?? undefined}
                      subtitles={subtitleTracks}
                    />
                  );
                })()}
              </div>
            ) : (
              <div className="panel video-loading-panel">
                <p>加载中...</p>
              </div>
            )}
          </section>

          <aside className="video-play-sidebar panel">
            {selectedVideo && (
              <div className="detail-copy">
                <div className="video-play-info">
                  <h1>{selectedVideo.title}</h1>
                  <div className="micro-row wrap compact-actions video-detail-actions">
                    <button className="compact-button" onClick={() => openVideoEditModal()}>
                      <Edit3 size={14} aria-hidden="true" />
                      编辑信息
                    </button>
                  </div>
                  
                  <div className="bili-up-list">
                    {selectedVideo.people.map((person) => (
                      <div className="bili-up-item" key={person.id}>
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <span>{person.name}</span>
                      </div>
                    ))}
                  </div>

                  <div className="micro-row wrap video-tag-row">
                    {selectedVideo.category_tags.map((tag) => (
                      <span key={tag.id} className="pill muted">#{tag.name}</span>
                    ))}
                  </div>

                  <div className="video-meta-grid">
                    <span>{formatDate(selectedVideo.created_at)}</span>
                    <span>{videoStatusLabel(selectedVideo.status)}</span>
                    <span>{formatDurationSeconds(selectedVideo.duration_seconds)}</span>
                    <span>{formatResolution(selectedVideo.width, selectedVideo.height)}</span>
                  </div>

                  <div className="description-box">
                    {selectedVideo.description || "无简介"}
                  </div>

                  <div className="subtitle-panel">
                    <div className="section-head compact-head">
                      <div>
                        <p className="eyebrow">字幕</p>
                        <h2>中文字幕</h2>
                      </div>
                    </div>
                    {selectedVideo.subtitle_tracks.length > 0 ? (
                      selectedVideo.subtitle_tracks.map((track) => (
                        <div className={`subtitle-status subtitle-status-${track.status}`} key={track.id}>
                          <strong>{track.label}</strong>
                          <span>{subtitleTrackStatusLabel(track.status)}</span>
                          {track.error_message && <small>{track.error_message}</small>}
                          {track.status === "ready" && track.srt_url && (
                            <a className="compact-button subtitle-download-link" href={track.srt_url}>
                              <Download size={14} aria-hidden="true" />
                              下载 SRT
                            </a>
                          )}
                        </div>
                      ))
                    ) : (
                      <p className="subtitle-empty">当前视频还没有字幕。</p>
                    )}
                    <button
                      className="ghost-button"
                      disabled={busy || selectedVideo.subtitle_tracks.some((track) => ["pending", "running"].includes(track.status))}
                      onClick={() => void handleGenerateSelectedVideoSubtitles()}
                    >
                      生成中文字幕
                    </button>
                  </div>
                </div>

                <div className="section-head compact-head video-management-head">
                  <div>
                    <p className="eyebrow">视频管理</p>
                    <h2>封面与文件</h2>
                  </div>
                </div>

                <div className="video-cover-manager">
                  {selectedVideo.cover_url ? (
                    <img src={selectedVideo.cover_url} alt="视频封面" />
                  ) : (
                    <div className="video-cover-empty">暂无封面</div>
                  )}
                  <label className="cover-upload-button">
                    <input
                      type="file"
                      accept="image/*"
                      disabled={busy}
                      onChange={(event) => {
                        void handleReplaceVideoCover(event.target.files);
                        event.currentTarget.value = "";
                      }}
                    />
                    替换封面
                  </label>
                </div>
                
                <p><strong>文件:</strong> {selectedVideo.filename}</p>
                <p><strong>原始格式:</strong> {formatCodecs(selectedVideo.original_video_codec, selectedVideo.original_audio_codec, selectedVideo.status)}</p>
                <p><strong>播放格式:</strong> {formatCodecs(selectedVideo.video_codec, selectedVideo.audio_codec, selectedVideo.status)}</p>
                <p><strong>体积:</strong> {formatBytes(selectedVideo.size_bytes)}</p>
                <p>
                  {selectedVideo.faststart_applied ? "· 已完成 faststart 优化" : "· 未优化"}
                </p>
                <p>
                  {selectedVideo.seek_optimized
                    ? `· 已完成拖动优化${selectedVideo.seek_keyframe_interval_seconds ? `（关键帧约 ${selectedVideo.seek_keyframe_interval_seconds.toFixed(2)} 秒）` : ""}`
                    : "· 未完成拖动优化"}
                </p>
                {selectedVideo.processing_error && <p className="inline-error">优化错误：{selectedVideo.processing_error}</p>}

                <div className="video-playback-tools">
                  <button
                    className="ghost-button"
                    disabled={videoPlaybackDiagnosticsLoading || selectedVideo.status === "processing"}
                    onClick={() => void handleLoadVideoPlaybackDiagnostics()}
                  >
                    {videoPlaybackDiagnosticsLoading ? "诊断中..." : "读取播放诊断"}
                  </button>
                  <button
                    className="compact-button"
                    disabled={busy || selectedVideo.status === "processing"}
                    onClick={() => void handleOptimizeSelectedVideoPlayback()}
                  >
                    优化拖动流畅度
                  </button>
                </div>
                {videoPlaybackDiagnostics && (
                  <div className="video-playback-diagnostics">
                    <p><strong>播放链路:</strong> {videoPlaybackDiagnostics.expected_mode}</p>
                    <p><strong>MinIO:</strong> {videoPlaybackDiagnostics.presigned_url_host || videoPlaybackDiagnostics.minio_public_endpoint}</p>
                    <p><strong>对象:</strong> {formatBytes(videoPlaybackDiagnostics.object?.object_size_bytes ?? videoPlaybackDiagnostics.size_bytes)}</p>
                    <p><strong>码率:</strong> {videoPlaybackDiagnostics.object?.bitrate ? `${Math.round(videoPlaybackDiagnostics.object.bitrate / 1000)} kbps` : "未知"}</p>
                    <p><strong>Faststart:</strong> {videoPlaybackDiagnostics.object?.faststart === null || videoPlaybackDiagnostics.object?.faststart === undefined ? "未知" : videoPlaybackDiagnostics.object.faststart ? "是" : "否"}</p>
                    <p>
                      <strong>估算关键帧间隔:</strong>{" "}
                      {videoPlaybackDiagnostics.object?.estimated_keyframe_interval_seconds
                        ? `${videoPlaybackDiagnostics.object.estimated_keyframe_interval_seconds.toFixed(2)} 秒`
                        : "未知"}
                    </p>
                    {videoPlaybackDiagnostics.object_probe_error && <p className="inline-error">{videoPlaybackDiagnostics.object_probe_error}</p>}
                  </div>
                )}
                
                <button 
                  className="danger-button full-width-action" 
                  disabled={busy} 
                  onClick={() => {
                    void handleDeleteCurrentVideo().then((deleted) => {
                      if (deleted) window.close();
                    });
                  }}
                >
                  删除视频
                </button>
              </div>
            )}
          </aside>
        </main>
      )}

      {page === "home" && <Home />}

      {page === "gallery" && GalleryPageComponent()}

      {page === "similarity" && (
        <SimilarityReview
          persons={persons}
          canEdit={authSession.workspace.role === "owner" || Boolean(authSession.workspace.permissions.can_edit_gallery)}
          canDelete={authSession.workspace.role === "owner" || Boolean(authSession.workspace.permissions.can_delete_gallery)}
        />
      )}

      {page === "acquisition" && (
        <AcquisitionCenter
          canEdit={authSession.workspace.role === "owner" || Boolean(authSession.workspace.permissions.can_edit_gallery)}
          canAdd={authSession.workspace.role === "owner" || Boolean(authSession.workspace.permissions.can_add_gallery)}
          canDelete={authSession.workspace.role === "owner" || Boolean(authSession.workspace.permissions.can_delete_gallery)}
        />
      )}

      {page === "people" && PeoplePageComponent()}

      {page === "upload" && renderUploadPage()}

      {(page === "gallery" || page === "videos") && (
        <button className="floating-top-button" type="button" onClick={scrollToPageTop} aria-label="回到顶部" title="回到顶部">
          <ArrowUp size={24} aria-hidden="true" />
        </button>
      )}

      {isVideoUploadModalOpen && renderVideoUploadModal()}

      {isVideoEditModalOpen && selectedVideo && (
        <div className="modal-backdrop" onClick={() => setIsVideoEditModalOpen(false)}>
          <div className="video-edit-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">编辑视频</p>
                <h2>修改信息</h2>
              </div>
              <button className="close-modal" onClick={() => setIsVideoEditModalOpen(false)}>关闭</button>
            </div>
            <div className="stack-editor">
              <input value={editVideoTitle} onChange={(event) => setEditVideoTitle(event.target.value)} placeholder="视频标题" />
              <textarea
                className="rich-text-editor compact"
                value={editVideoDescription}
                onChange={(event) => setEditVideoDescription(event.target.value)}
                placeholder="视频简介"
              />
            </div>
            <div className="editor-block">
              <label>分区</label>
              <div className="chip-cloud compact">
                {videoCategoryTags.map((tag) => (
                  <button
                    key={tag.id}
                    className={editVideoCategoryIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                    onClick={() => {
                      setEditVideoCategoryIds((current) =>
                        current.includes(tag.id) ? current.filter((id) => id !== tag.id) : [...current, tag.id]
                      );
                    }}
                  >
                    #{tag.name}
                  </button>
                ))}
              </div>
            </div>
            <div className="editor-block">
              <label>UP主</label>
              <div className="video-person-cloud compact">
                {videoPeople.map((person) => (
                  <button
                    key={person.id}
                    className={editVideoPersonIds.includes(person.id) ? "video-person-chip active" : "video-person-chip"}
                    onClick={() => {
                      setEditVideoPersonIds((current) =>
                        current.includes(person.id) ? current.filter((id) => id !== person.id) : [...current, person.id]
                      );
                    }}
                  >
                    {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <span>{person.name.slice(0, 1)}</span>}
                    <b>{person.name}</b>
                  </button>
                ))}
              </div>
            </div>
            <div className="modal-actions">
              <button className="ghost-button" onClick={() => setIsVideoEditModalOpen(false)}>取消</button>
              <button disabled={busy} onClick={() => void handleSaveVideoEdit()}>保存</button>
            </div>
          </div>
        </div>
      )}

      {isCategoryManageModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsCategoryManageModalOpen(false)}>
          <div className="manage-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">管理分区</p>
                <h2>视频分类</h2>
              </div>
              <button className="close-modal" onClick={() => setIsCategoryManageModalOpen(false)}>关闭</button>
            </div>
            <div className="inline-editor flush-editor">
              <input value={newManageCategoryName} onChange={(event) => setNewManageCategoryName(event.target.value)} placeholder="新分区名称" />
              <button disabled={busy || !newManageCategoryName.trim()} onClick={() => void handleCreateManageCategory()}>创建</button>
            </div>
            <div className="manage-list">
              {videoCategoryTags.map((tag) => (
                <div key={tag.id} className="manage-item">
                  {editingCategoryId === tag.id ? (
                    <div className="inline-editor flush-editor flex-editor">
                      <input value={editingCategoryName} onChange={(event) => setEditingCategoryName(event.target.value)} placeholder="分区名称" />
                      <button disabled={busy || !editingCategoryName.trim()} onClick={() => void handleUpdateManageCategory(tag.id)}>保存</button>
                      <button className="ghost-button" onClick={() => { setEditingCategoryId(null); setEditingCategoryName(""); }}>取消</button>
                    </div>
                  ) : (
                    <>
                      <span>#{tag.name}</span>
                      <div className="micro-row wrap mini-actions">
                        <button className="mini-button" onClick={() => { setEditingCategoryId(tag.id); setEditingCategoryName(tag.name); }}>编辑</button>
                        <button className="mini-button danger-text" onClick={() => void handleDeleteManageCategory(tag.id)}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {videoCategoryTags.length === 0 && <p className="tip">暂无分区</p>}
            </div>
          </div>
        </div>
      )}

      {isVideoPersonManageModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsVideoPersonManageModalOpen(false)}>
          <div className="manage-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">管理UP主</p>
                <h2>视频人物</h2>
              </div>
              <button className="close-modal" onClick={() => setIsVideoPersonManageModalOpen(false)}>关闭</button>
            </div>
            <div className="stack-editor modal-stack">
              <input value={newManagePersonName} onChange={(event) => setNewManagePersonName(event.target.value)} placeholder="UP主名称" />
              <input value={newManagePersonNote} onChange={(event) => setNewManagePersonNote(event.target.value)} placeholder="备注（可选）" />
              <div className="inline-editor flush-editor">
                <input type="file" accept="image/*" onChange={(event) => setNewManagePersonAvatar(event.target.files?.[0] ?? null)} />
                <button disabled={busy || !newManagePersonName.trim()} onClick={() => void handleCreateManagePerson()}>创建</button>
              </div>
            </div>
            <div className="manage-list">
              {videoPeople.map((person) => (
                <div key={person.id} className="manage-item">
                  {editingPersonId === person.id ? (
                    <div className="stack-editor flex-editor">
                      <input value={editingPersonName} onChange={(event) => setEditingPersonName(event.target.value)} placeholder="UP主名称" />
                      <input value={editingPersonNote} onChange={(event) => setEditingPersonNote(event.target.value)} placeholder="备注（可选）" />
                      <div className="inline-editor flush-editor">
                        <input type="file" accept="image/*" onChange={(event) => setEditingPersonAvatar(event.target.files?.[0] ?? null)} />
                        <button disabled={busy || !editingPersonName.trim()} onClick={() => void handleUpdateManagePerson(person.id)}>保存</button>
                        <button className="ghost-button" onClick={() => { setEditingPersonId(null); setEditingPersonName(""); setEditingPersonNote(""); setEditingPersonAvatar(null); }}>取消</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="manage-person-info">
                        {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                        <div>
                          <strong>{person.name}</strong>
                          {person.note && <small>{person.note}</small>}
                        </div>
                      </div>
                      <div className="micro-row wrap mini-actions">
                        <button className="mini-button" onClick={() => { setEditingPersonId(person.id); setEditingPersonName(person.name); setEditingPersonNote(person.note || ""); setEditingPersonAvatar(null); }}>编辑</button>
                        <button className="mini-button danger-text" onClick={() => void handleDeleteManagePerson(person.id)}>删除</button>
                      </div>
                    </>
                  )}
                </div>
              ))}
              {videoPeople.length === 0 && <p className="tip">暂无UP主</p>}
            </div>
          </div>
        </div>
      )}

      {galleryExportModalOpen && (
        <div className="modal-backdrop" onClick={() => setGalleryExportModalOpen(false)}>
          <div className="export-modal" onClick={(event) => event.stopPropagation()}>
            <div className="section-head">
              <div>
                <p className="eyebrow">导出展示图</p>
                <h2>选择导出范围</h2>
              </div>
              <button className="lightbox-close" onClick={() => setGalleryExportModalOpen(false)}>
                关闭
              </button>
            </div>

            <div className="export-choice-row">
              <button
                className={galleryExportScope === "filtered" ? "soft-chip active" : "soft-chip"}
                onClick={() => setGalleryExportScope("filtered")}
              >
                自定义范围
              </button>
              <button
                className={galleryExportScope === "all" ? "soft-chip active" : "soft-chip"}
                onClick={() => setGalleryExportScope("all")}
              >
                全部展示图
              </button>
              <span>
                {galleryExportScope === "all"
                  ? "将导出图库中的全部展示图"
                  : `按 ${galleryExportPersonIds.length} 个人物、${galleryExportTagIds.length} 个普通标签导出`}
              </span>
            </div>

            <div className={galleryExportScope === "all" ? "export-filter-grid disabled" : "export-filter-grid"}>
              <section className="export-filter-block">
                <div className="filter-section-head">
                  <strong>人物标签</strong>
                  <span>{galleryExportPersonIds.length} 已选</span>
                </div>
                <div className="export-chip-cloud">
                  {sortByPinyinName(persons).map((person) => (
                    <button
                      key={`export-person-${person.id}`}
                      className={galleryExportPersonIds.includes(person.id) ? "soft-chip active" : "soft-chip"}
                      disabled={galleryExportScope === "all"}
                      onClick={() => handleToggleGalleryExportPerson(person.id)}
                    >
                      {person.display_name}
                    </button>
                  ))}
                  {persons.length === 0 && <span className="filter-empty">没有人物标签</span>}
                </div>
              </section>

              <section className="export-filter-block">
                <div className="filter-section-head">
                  <strong>普通标签</strong>
                  <span>{galleryExportTagIds.length} 已选</span>
                </div>
                <div className="export-chip-cloud compact">
                  {normalTags.map((tag) => (
                    <button
                      key={`export-tag-${tag.id}`}
                      className={galleryExportTagIds.includes(tag.id) ? "soft-chip active" : "soft-chip"}
                      disabled={galleryExportScope === "all"}
                      onClick={() => handleToggleGalleryExportTag(tag.id)}
                    >
                      #{tag.name}
                    </button>
                  ))}
                  {normalTags.length === 0 && <span className="filter-empty">没有普通标签</span>}
                </div>
              </section>
            </div>

            <div className="modal-actions">
              <button
                onClick={() => {
                  setGalleryExportScope("filtered");
                  setGalleryExportPersonIds([]);
                  setGalleryExportTagIds([]);
                }}
              >
                清空筛选
              </button>
              <button disabled={busy} onClick={handleExportGalleryPhotos}>
                导出 ZIP
              </button>
            </div>
          </div>
        </div>
      )}

      {lightboxPhoto && (
        <PhotoLightbox
          shellClassName={`gallery-lightbox${lightboxPhoto.is_rich_text ? " rich-lightbox" : ""}`}
          meta={lightboxMeta}
          busy={busy}
          keyboardEnabled={!lightboxEditMode}
          canGoPrevious={canGoPrev}
          canGoNext={canGoNext}
          previousLabel={isFirstOfPage && hasPrevPage ? "上一页" : undefined}
          nextLabel={isLastOfPage && hasNextPage ? "下一页" : undefined}
          onClose={closeGalleryLightbox}
          onPrevious={goPrevLightbox}
          onNext={goNextLightbox}
        >
            {lightboxPhoto.is_rich_text ? (
              <div className="rich-lightbox-layout">
                <div className="rich-lightbox-image-wrap">
                  <img className="lightbox-image" src={lightboxPhoto.original_url} alt="图文大图预览" />
                </div>
                <aside className="rich-lightbox-copy">
                  <h3>图文内容</h3>
                  {lightboxEditMode ? (
                    <textarea
                      className="rich-text-editor lightbox-editor"
                      value={lightboxRichTextDraft}
                      onChange={(event) => setLightboxRichTextDraft(event.target.value)}
                      placeholder="可在此编辑图文文本"
                    />
                  ) : (
                    <p>{lightboxPhoto.rich_text || "未识别到文本，点击编辑按钮手动补录。"}</p>
                  )}
                  <div className="micro-row">
                    <span>OCR状态：{lightboxPhoto.ocr_status ?? "unknown"}</span>
                    {lightboxEditMode ? (
                      <button
                        disabled={busy}
                        onClick={() => {
                          void handleSaveLightboxRichText();
                          setLightboxEditMode(false);
                        }}
                      >
                        保存图文文本
                      </button>
                    ) : (
                      <button
                        disabled={busy}
                        onClick={() => {
                          setLightboxRichTextDraft(lightboxPhoto.rich_text || "");
                          setLightboxEditMode(true);
                        }}
                      >
                        编辑图文文本
                      </button>
                    )}
                  </div>
                  <div className="micro-row wrap">
                    {lightboxPhoto.persons.map((person) => (
                      <small key={`lb-p-${lightboxPhoto.id}-${person.person_id}`} className={person.is_unknown ? "pill unknown" : "pill"}>
                        {person.person_name}
                      </small>
                    ))}
                  </div>
                  <div className="micro-row wrap">
                    {sortByPinyinName(lightboxPhoto.tags).map((tag) => (
                      <small key={`lb-t-${lightboxPhoto.id}-${tag.id}`} className="pill muted">
                        #{tag.name}
                      </small>
                    ))}
                  </div>
                </aside>
              </div>
            ) : (
              <img className="lightbox-image" src={lightboxPhoto.original_url} alt="大图预览" />
            )}
        </PhotoLightbox>
      )}

      {recognitionNotice && (
        <div className="recognition-notice" role="status" aria-live="polite">
          <div>
            <strong>重新识别完成</strong>
            <span>{recognitionNotice.message}</span>
          </div>
          <button type="button" onClick={() => setRecognitionNotice(null)}>知道了</button>
          <i aria-hidden="true" />
        </div>
      )}
      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}
