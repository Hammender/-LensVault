import { useEffect, useMemo, useRef, useState } from "react";

import Statistics from "./Statistics";
import BiliVideoPlayer from "./BiliVideoPlayer";
import { sortByPinyinName } from "./sort";
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
  getVideo,
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
  listVideoCategoryTags,
  listVideoPeople,
  listVideos,
  renamePerson,
  replaceVideoCover,
  reRecognizeGalleryPhoto,
  reRecognizeUnknownGalleryPhotos,
  updateGalleryPhotoRichText,
  uploadVideoPart,
  unbindPersonTag,
  type GalleryExportScope,
  type GalleryUploadMetadata
} from "./api";
import type {
  GalleryPhotoDetail,
  GalleryPhotoListItem,
  Person,
  SamplePhoto,
  Tag,
  Task,
  VideoCategoryTag,
  VideoDetail,
  VideoItem,
  VideoPerson,
  VideoUploadSession
} from "./types";

type PageKey = "gallery" | "people" | "upload" | "videos" | "statistics" | "video-play";

type PendingSampleUpload = {
  file: File;
  previewUrl: string;
};

type PendingGalleryUpload = {
  file: File;
  previewUrl: string;
  personNamesText: string;
  tagNamesText: string;
  richText: string;
};

type UploadMode = "normal" | "rich";

const galleryPageSize = 20;
const videoPageSize = 12;
const videoPartSize = 16 * 1024 * 1024;
const videoResumeStorageKey = "pictureshow-video-upload-session";
const videoPartUploadMaxAttempts = 4;
const videoPartUploadRetryDelayMs = 1200;
const videoSeekSeconds = 10;
const videoSeekLargeSeconds = 30;
const videoLongPressDelayMs = 300;
const videoLongPressRate = 3;

function formatDate(value: string | null | undefined): string {
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

function formatBytes(value: number): string {
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

function formatDurationSeconds(value: number | null | undefined): string {
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

function formatResolution(width: number | null | undefined, height: number | null | undefined): string {
  if (!width || !height) {
    return "分辨率未知";
  }
  return `${width}x${height}`;
}

function formatCodecs(videoCodec: string | null | undefined, audioCodec: string | null | undefined): string {
  const video = videoCodec || "未知视频编码";
  const audio = audioCodec || "无音频/未知音频";
  return `${video} / ${audio}`;
}

function isTextEditingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) {
    return false;
  }
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

function videoStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    uploaded: "等待优化",
    processing: "优化中",
    ready: "可播放",
    processing_failed: "优化失败"
  };
  return labels[status] ?? status;
}

function routeFromHash(): PageKey {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash.startsWith("video-play/")) {
    return "video-play";
  }
  if (hash === "people" || hash === "upload" || hash === "videos" || hash === "statistics") {
    return hash;
  }
  return "gallery";
}

function setRoute(page: PageKey) {
  window.location.hash = `/${page}`;
}

function splitCommaList(input: string): string[] {
  return Array.from(
    new Set(
      input
        .split(/[，,]/)
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

export default function App() {
  const [page, setPageState] = useState<PageKey>(() => routeFromHash());
  const [playVideoId, setPlayVideoId] = useState<string | null>(null);
  const [isVideoUploadModalOpen, setIsVideoUploadModalOpen] = useState(false);
  const [persons, setPersons] = useState<Person[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [galleryPhotos, setGalleryPhotos] = useState<GalleryPhotoListItem[]>([]);
  const [galleryTotal, setGalleryTotal] = useState(0);
  const [galleryOffset, setGalleryOffset] = useState(0);
  const [gallerySelectionMode, setGallerySelectionMode] = useState(false);
  const [selectedGalleryPhotoIds, setSelectedGalleryPhotoIds] = useState<number[]>([]);
  const [galleryExportModalOpen, setGalleryExportModalOpen] = useState(false);
  const [galleryExportScope, setGalleryExportScope] = useState<GalleryExportScope>("filtered");
  const [galleryExportPersonIds, setGalleryExportPersonIds] = useState<number[]>([]);
  const [galleryExportTagIds, setGalleryExportTagIds] = useState<number[]>([]);
  const [lightboxPhotoId, setLightboxPhotoId] = useState<number | null>(null);
  const [selectedPersonIds, setSelectedPersonIds] = useState<number[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [excludePersonIds, setExcludePersonIds] = useState<number[]>([]);
  const [excludeTagIds, setExcludeTagIds] = useState<number[]>([]);
  const [personSearch, setPersonSearch] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [showUnknownPersons, setShowUnknownPersons] = useState(false);
  const [showExcludePersons, setShowExcludePersons] = useState(false);
  const [showExcludeTags, setShowExcludeTags] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState<GalleryPhotoDetail | null>(null);
  const [manualPersonId, setManualPersonId] = useState("");
  const [manualTagId, setManualTagId] = useState("");
  const [manualTagName, setManualTagName] = useState("");
  const [richTextDraft, setRichTextDraft] = useState("");
  const [lightboxRichTextDraft, setLightboxRichTextDraft] = useState("");
  const [lightboxEditMode, setLightboxEditMode] = useState(false);
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
  const [peopleSearch, setPeopleSearch] = useState("");
  const [peopleBatchDeleteMode, setPeopleBatchDeleteMode] = useState(false);
  const [selectedPersonDeleteIds, setSelectedPersonDeleteIds] = useState<number[]>([]);
  const [samples, setSamples] = useState<SamplePhoto[]>([]);
  const [personTags, setPersonTags] = useState<Tag[]>([]);
  const [personTagSelectId, setPersonTagSelectId] = useState("");
  const [personTagName, setPersonTagName] = useState("");
  const [newPersonName, setNewPersonName] = useState("");
  const [renameValue, setRenameValue] = useState("");
  const [task, setTask] = useState<Task | null>(null);
  const [pendingSampleUploads, setPendingSampleUploads] = useState<PendingSampleUpload[]>([]);
  const [pendingGalleryUploads, setPendingGalleryUploads] = useState<PendingGalleryUpload[]>([]);
  const [batchApplyPersonNames, setBatchApplyPersonNames] = useState("");
  const [batchApplyTagNames, setBatchApplyTagNames] = useState("");
  const [uploadMode, setUploadMode] = useState<UploadMode>("normal");
  const [importTask, setImportTask] = useState<Task | null>(null);
  const [galleryImportTask, setGalleryImportTask] = useState<Task | null>(null);
  const [videoItems, setVideoItems] = useState<VideoItem[]>([]);
  const [videoTotal, setVideoTotal] = useState(0);
  const [videoOffset, setVideoOffset] = useState(0);
  const [videoCategoryTags, setVideoCategoryTags] = useState<VideoCategoryTag[]>([]);
  const [videoPeople, setVideoPeople] = useState<VideoPerson[]>([]);
  const [selectedVideoCategoryIds, setSelectedVideoCategoryIds] = useState<number[]>([]);
  const [selectedVideoPersonIds, setSelectedVideoPersonIds] = useState<number[]>([]);
  const [videoSearch, setVideoSearch] = useState("");
  const [selectedVideo, setSelectedVideo] = useState<VideoDetail | null>(null);
  const [videoPlayerUrl, setVideoPlayerUrl] = useState("");
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoTitle, setVideoTitle] = useState("");
  const [videoDescription, setVideoDescription] = useState("");
  const [videoUploadCategoryIds, setVideoUploadCategoryIds] = useState<number[]>([]);
  const [videoUploadPersonIds, setVideoUploadPersonIds] = useState<number[]>([]);
  const [videoUploadNewCategories, setVideoUploadNewCategories] = useState("");
  const [videoUploadProgress, setVideoUploadProgress] = useState(0);
  const [videoUploadSession, setVideoUploadSession] = useState<VideoUploadSession | null>(null);
  const [newVideoCategoryName, setNewVideoCategoryName] = useState("");
  const [newVideoPersonName, setNewVideoPersonName] = useState("");
  const [newVideoPersonNote, setNewVideoPersonNote] = useState("");
  const [newVideoPersonAvatar, setNewVideoPersonAvatar] = useState<File | null>(null);
  const importFileRef = useRef<HTMLInputElement | null>(null);
  const galleryImportFileRef = useRef<HTMLInputElement | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jumpPageInput, setJumpPageInput] = useState("");
  const peopleMainRef = useRef<HTMLElement | null>(null);

  const richTag = useMemo(() => tags.find((tag) => tag.name === "图文") ?? null, [tags]);
  const normalTags = useMemo(() => sortByPinyinName(tags.filter((tag) => !tag.is_system)), [tags]);

  const filteredPersons = useMemo(() => {
    const keyword = personSearch.trim().toLowerCase();
    if (!keyword) {
      return persons;
    }
    return persons.filter((person) => person.display_name.toLowerCase().includes(keyword));
  }, [personSearch, persons]);

  const selectedFilterPersons = useMemo(
    () => persons.filter((person) => selectedPersonIds.includes(person.id)),
    [persons, selectedPersonIds]
  );

  const knownFilterPersons = useMemo(
    () => filteredPersons.filter((person) => !person.is_unknown && !selectedPersonIds.includes(person.id)),
    [filteredPersons, selectedPersonIds]
  );

  const unknownFilterPersons = useMemo(
    () => filteredPersons.filter((person) => person.is_unknown && !selectedPersonIds.includes(person.id)),
    [filteredPersons, selectedPersonIds]
  );

  const allFilteredUnknownPersons = useMemo(
    () => filteredPersons.filter((person) => person.is_unknown),
    [filteredPersons]
  );

  const personSearchActive = personSearch.trim().length > 0;
  const visibleUnknownFilterPersons = showUnknownPersons || personSearchActive ? unknownFilterPersons : [];
  const selectedUnknownPersonCount = selectedFilterPersons.filter((person) => person.is_unknown).length;
  const allFilteredUnknownSelected =
    allFilteredUnknownPersons.length > 0 &&
    allFilteredUnknownPersons.every((person) => selectedPersonIds.includes(person.id));

  const filteredTags = useMemo(() => {
    const keyword = tagSearch.trim().toLowerCase();
    if (!keyword) {
      return sortByPinyinName(tags);
    }
    return sortByPinyinName(tags.filter((tag) => tag.name.toLowerCase().includes(keyword)));
  }, [tagSearch, tags]);

  const excludedFilterPersons = useMemo(
    () => persons.filter((person) => excludePersonIds.includes(person.id)),
    [persons, excludePersonIds]
  );

  const excludedFilterTags = useMemo(
    () => tags.filter((tag) => excludeTagIds.includes(tag.id)),
    [tags, excludeTagIds]
  );

  const availableExcludePersons = useMemo(
    () => persons.filter((person) => !selectedPersonIds.includes(person.id) && !excludePersonIds.includes(person.id)),
    [persons, selectedPersonIds, excludePersonIds]
  );

  const availableExcludeKnownPersons = useMemo(
    () => availableExcludePersons.filter((person) => !person.is_unknown),
    [availableExcludePersons]
  );

  const availableExcludeUnknownPersons = useMemo(
    () => availableExcludePersons.filter((person) => person.is_unknown),
    [availableExcludePersons]
  );

  const availableExcludeTags = useMemo(
    () => sortByPinyinName(tags.filter((tag) => !selectedTagIds.includes(tag.id) && !excludeTagIds.includes(tag.id))),
    [tags, selectedTagIds, excludeTagIds]
  );

  const filteredPeopleInLibrary = useMemo(() => {
    const keyword = peopleSearch.trim().toLowerCase();
    if (!keyword) {
      return persons;
    }
    return persons.filter((person) => person.display_name.toLowerCase().includes(keyword));
  }, [peopleSearch, persons]);

  const unknownPersonCount = useMemo(() => persons.filter((person) => person.is_unknown).length, [persons]);
  const orphanUnknownPersons = useMemo(
    () => persons.filter((person) => person.is_unknown && person.sample_count === 0 && person.gallery_photo_count === 0),
    [persons]
  );
  const orphanUnknownCount = orphanUnknownPersons.length;

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
  const videoTotalPages = Math.max(1, Math.ceil(videoTotal / videoPageSize));
  const videoCurrentPage = Math.floor(videoOffset / videoPageSize) + 1;

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
      setRoute("gallery");
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
    if (!selectedVideo || !["uploaded", "processing"].includes(selectedVideo.status)) {
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
  }, [selectedVideo?.id, selectedVideo?.status]);

  useEffect(() => {
    if (!selectedVideo) {
      setVideoPlayerUrl("");
      return;
    }
    setVideoPlayerUrl(selectedVideo.play_url || selectedVideo.stream_url);
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
    if (!task || task.status === "completed" || task.status === "failed") {
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
    if (!importTask || importTask.status === "completed" || importTask.status === "failed") {
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
    if (!galleryImportTask || galleryImportTask.status === "completed" || galleryImportTask.status === "failed") {
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
      setManualTagId("");
      setManualTagName("");
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
    setPendingSampleUploads((current) => [
      ...current,
      ...Array.from(files).map((file) => ({ file, previewUrl: URL.createObjectURL(file) }))
    ]);
  }

  async function handleConfirmSampleUpload() {
    if (!selectedPerson || pendingSampleUploads.length === 0) {
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
    if (!window.confirm(`确认删除选中的 ${selectedPersonDeleteIds.length} 个人物吗？这会删除其样本图、关联向量与对象存储文件。`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeletePersons(selectedPersonDeleteIds);
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
    if (!window.confirm(`确认删除人物「${selectedPerson.display_name}」吗？`)) {
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

  async function handleDeleteAllUnknownPersons() {
    const unknownIds = orphanUnknownPersons.map((person) => person.id);
    if (unknownIds.length === 0) {
      return;
    }
    if (
      !window.confirm(
        `确定清理 ${unknownIds.length} 个无任何图库和样本关联的未知人物吗？\n删除后不可恢复。`
      )
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeletePersons(unknownIds);
      setSelectedPersonDeleteIds((current) => current.filter((id) => !unknownIds.includes(id)));
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "清空未知人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleReRecognizeAllUnknownPhotos() {
    if (
      !window.confirm("确认重新识别所有带未知人物标签的图片吗？识别后的新人物标签会覆盖旧标签。")
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
    setBusy(true);
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
      setBusy(false);
    }
  }

  function handlePickVideoFile(files: FileList | null) {
    const file = files?.[0] ?? null;
    setVideoFile(file);
    if (file && !videoTitle.trim()) {
      setVideoTitle(file.name.replace(/\.[^.]+$/, ""));
    }
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


  async function handleDeleteCurrentVideo() {
    if (!selectedVideo) {
      return;
    }
    if (!window.confirm(`确认删除视频「${selectedVideo.title}」吗？`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteVideo(selectedVideo.id);
      setSelectedVideo(null);
      setVideoPlayerUrl("");
      await refreshVideos(videoOffset, selectedVideoCategoryIds, selectedVideoPersonIds, videoSearch);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "删除视频失败。");
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

  async function resolveVideoUploadSession(file: File): Promise<VideoUploadSession> {
    const raw = window.localStorage.getItem(videoResumeStorageKey);
    if (raw) {
      try {
        const saved = JSON.parse(raw) as { sessionId: string; name: string; size: number; lastModified: number };
        if (saved.name === file.name && saved.size === file.size && saved.lastModified === file.lastModified) {
          const existing = await getVideoUploadSession(saved.sessionId);
          setVideoUploadSession(existing);
          return existing;
        }
      } catch {
        window.localStorage.removeItem(videoResumeStorageKey);
      }
    }
    const session = await createVideoUploadSession({
      title: videoTitle.trim(),
      description: videoDescription.trim() || null,
      filename: file.name,
      content_type: file.type || "video/mp4",
      size_bytes: file.size,
      part_size: videoPartSize
    });
    window.localStorage.setItem(
      videoResumeStorageKey,
      JSON.stringify({ sessionId: session.id, name: file.name, size: file.size, lastModified: file.lastModified })
    );
    setVideoUploadSession(session);
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
    if (!videoFile || !videoTitle.trim()) {
      return;
    }
    if (!videoFile.name.toLowerCase().endsWith(".mp4")) {
      setError("当前版本仅支持 MP4 视频。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      let session = await resolveVideoUploadSession(videoFile);
      const uploaded = new Set(session.uploaded_parts);
      setVideoUploadSession(session);
      for (let index = 0; index < session.total_parts; index += 1) {
        if (uploaded.has(index)) {
          setVideoUploadProgress(Math.round(((index + 1) / session.total_parts) * 100));
          continue;
        }
        const start = index * session.part_size;
        const end = Math.min(start + session.part_size, videoFile.size);
        await uploadVideoPartWithRetry(session.id, index, videoFile.slice(start, end), videoFile.name);
        uploaded.add(index);
        const uploadedParts = Array.from(uploaded).sort((left, right) => left - right);
        session = { ...session, uploaded_parts: uploadedParts };
        setVideoUploadSession(session);
        setVideoUploadProgress(Math.round((uploadedParts.length / session.total_parts) * 100));
      }
      session = await getVideoUploadSession(session.id);
      setVideoUploadSession(session);
      await completeVideoUpload(session.id, {
        category_tag_ids: videoUploadCategoryIds,
        category_tag_names: splitCommaList(videoUploadNewCategories),
        person_ids: videoUploadPersonIds
      });
      window.localStorage.removeItem(videoResumeStorageKey);
      setVideoFile(null);
      setVideoTitle("");
      setVideoDescription("");
      setVideoUploadCategoryIds([]);
      setVideoUploadPersonIds([]);
      setVideoUploadNewCategories("");
      setVideoUploadSession(null);
      setVideoUploadProgress(0);
      setIsVideoUploadModalOpen(false);
      void refreshVideoTaxonomy();
      void refreshVideos(0, [], [], "");
    } catch (cause) {
      const message = cause instanceof Error ? cause.message : "视频上传失败。";
      setError(`${message}。已保留续传会话，可再次点击开始上传继续。`);
    } finally {
      setBusy(false);
    }
  }

  async function handleCancelVideoUpload() {
    if (!videoUploadSession) {
      window.localStorage.removeItem(videoResumeStorageKey);
      setVideoUploadProgress(0);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await cancelVideoUpload(videoUploadSession.id);
      window.localStorage.removeItem(videoResumeStorageKey);
      setVideoUploadSession(null);
      setVideoUploadProgress(0);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "取消视频上传失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleAddPhotoPerson() {
    if (!selectedPhoto || !manualPersonId) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await addGalleryPhotoPerson(selectedPhoto.id, Number(manualPersonId));
      setSelectedPhoto(detail);
      setManualPersonId("");
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "添加人物标签失败。");
    } finally {
      setBusy(false);
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

  async function handleAddPhotoTag() {
    if (!selectedPhoto || (!manualTagId && !manualTagName.trim())) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const detail = await addGalleryPhotoTag(
        selectedPhoto.id,
        manualTagId ? { tagId: Number(manualTagId) } : { name: manualTagName.trim() }
      );
      setSelectedPhoto(detail);
      setManualTagId("");
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
    if (!window.confirm(`确认删除选中的 ${selectedGalleryPhotoIds.length} 张图库图片吗？这会删除图片文件、识别记录和向量数据。`)) {
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
    if (!window.confirm(`确认删除当前图片（ID: ${selectedPhoto.id}）吗？`)) {
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

  const availablePersonsForPhoto = selectedPhoto
    ? persons.filter((person) => !selectedPhoto.persons.some((tag) => tag.person_id === person.id))
    : persons;

  const selectedPhotoTags = selectedPhoto ? sortByPinyinName(selectedPhoto.tags) : [];

  const availableTagsForPhoto = selectedPhoto
    ? sortByPinyinName(tags.filter((tag) => !tag.is_system && !selectedPhoto.tags.some((item) => item.id === tag.id)))
    : sortByPinyinName(tags.filter((tag) => !tag.is_system));

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

  useEffect(() => {
    if (!lightboxPhoto) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (busy) return;
      if (lightboxEditMode) return;
      if (event.key === "Escape") {
        closeGalleryLightbox();
      } else if (event.key === "ArrowLeft") {
        void goPrevLightbox();
      } else if (event.key === "ArrowRight") {
        void goNextLightbox();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lightboxPhoto, lightboxIndex, canGoPrev, canGoNext, hasPrevPage, hasNextPage, galleryOffset, busy, lightboxEditMode]);

  return (
    <div className="app-shell">
      <div className="sunwash sunwash-a" />
      <div className="sunwash sunwash-b" />

      <header className="topbar">
        <div>
          <p className="eyebrow">Local Face Archive</p>
          <h1>PictureShow</h1>
          <p className="lead">将人物样本库、展示图库和展示图上传拆成独立页面，围绕本地识别与人工修正形成完整闭环。</p>
        </div>
        <nav className="nav-tabs">
          {[
            ["gallery", "页面 A · 展示图库"],
            ["people", "页面 B · 人物样本库"],
            ["upload", "页面 C · 展示图上传"],
            ["videos", "页面 D · 视频库"],
            ["statistics", "页面 E · 数据统计"]
          ].map(([key, label]) => (
            <button
              key={key}
              className={page === key ? "nav-tab active" : "nav-tab"}
              onClick={() => {
                setPageState(key as PageKey);
                setRoute(key as PageKey);
              }}
            >
              {label}
            </button>
          ))}
        </nav>
      </header>

      {page === "statistics" && <Statistics />}

      {page === "videos" && (
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
            <button className="primary" onClick={() => setIsVideoUploadModalOpen(true)}>
              上传视频
            </button>
          </div>

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
                    <span className="placeholder">MP4</span>
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
                    {video.people.length === 0 && <span className="muted" style={{fontSize: '0.8rem'}}>无UP主</span>}
                  </div>
                  <div className="bili-video-meta">
                    <span>{formatDate(video.created_at)}</span>
                  </div>
                </div>
              </article>
            ))}
          </div>

          {videoTotal > 0 && (
            <div className="pagination-row" style={{ marginTop: 'auto' }}>
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

          {isVideoUploadModalOpen && (
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
                  <input type="file" accept="video/mp4,.mp4" onChange={(event) => handlePickVideoFile(event.target.files)} />
                  <strong>{videoFile ? videoFile.name : "选择 MP4 视频"}</strong>
                  <span>{videoFile ? formatBytes(videoFile.size) : "支持长视频分片上传，刷新后重新选择同一文件可续传。"}</span>
                </label>

                <div className="stack-editor">
                  <input value={videoTitle} onChange={(event) => setVideoTitle(event.target.value)} placeholder="视频名字" />
                  <textarea
                    className="rich-text-editor compact"
                    value={videoDescription}
                    onChange={(event) => setVideoDescription(event.target.value)}
                    placeholder="视频简介"
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

                <div className="video-progress">
                  <strong>{videoUploadProgress}%</strong>
                  <div className="meter"><span style={{ width: `${videoUploadProgress}%` }} /></div>
                  {videoUploadSession && <small>{videoUploadSession.uploaded_parts.length} / {videoUploadSession.total_parts} 分片</small>}
                </div>

                <div className="micro-row wrap">
                  <button disabled={busy || !videoFile || !videoTitle.trim()} onClick={() => void handleConfirmVideoUpload()}>
                    开始上传
                  </button>
                  <button className="ghost-button" disabled={busy} onClick={() => void handleCancelVideoUpload()}>
                    清理续传会话
                  </button>
                </div>

                <div className="editor-block">
                  <label>新增视频类别</label>
                  <div className="inline-editor">
                    <input value={newVideoCategoryName} onChange={(event) => setNewVideoCategoryName(event.target.value)} placeholder="类别名" />
                    <button disabled={busy || !newVideoCategoryName.trim()} onClick={() => void handleCreateVideoCategory()}>
                      新增
                    </button>
                  </div>
                </div>

                <div className="editor-block">
                  <label>新增视频人物</label>
                  <input value={newVideoPersonName} onChange={(event) => setNewVideoPersonName(event.target.value)} placeholder="人物名" />
                  <textarea
                    className="rich-text-editor compact"
                    value={newVideoPersonNote}
                    onChange={(event) => setNewVideoPersonNote(event.target.value)}
                    placeholder="备注"
                  />
                  <input type="file" accept="image/*" onChange={(event) => setNewVideoPersonAvatar(event.target.files?.[0] ?? null)} />
                  <button disabled={busy || !newVideoPersonName.trim()} onClick={() => void handleCreateVideoPerson()}>
                    创建视频人物
                  </button>
                </div>
              </aside>
            </div>
          )}
        </main>
      )}

      {page === "video-play" && (
        <main className="video-play-page">
          <section className="video-play-main">
            {selectedVideo ? (
              <div className="panel" style={{ padding: '0', overflow: 'hidden' }}>
                  <BiliVideoPlayer src={videoPlayerUrl} poster={selectedVideo.cover_url ?? undefined} />
              </div>
            ) : (
              <div className="panel" style={{ height: '400px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <p>加载中...</p>
              </div>
            )}
            
            {selectedVideo && (
              <div className="video-play-info">
                <h1>{selectedVideo.title}</h1>
                <div className="micro-row wrap">
                  <span>{formatDate(selectedVideo.created_at)}</span>
                  <span>播放状态：{videoStatusLabel(selectedVideo.status)}</span>
                  <span>{formatDurationSeconds(selectedVideo.duration_seconds)}</span>
                  <span>{formatResolution(selectedVideo.width, selectedVideo.height)}</span>
                  <span>{formatBytes(selectedVideo.size_bytes)}</span>
                </div>
                
                <div className="bili-up-list" style={{ marginTop: '8px' }}>
                  {selectedVideo.people.map((person) => (
                    <div className="bili-up-item" key={person.id}>
                      {person.avatar_url ? <img src={person.avatar_url} alt={person.name} /> : <div className="fallback-avatar">{person.name.slice(0, 1)}</div>}
                      <span>{person.name}</span>
                    </div>
                  ))}
                </div>

                <div className="micro-row wrap" style={{ marginTop: '8px' }}>
                  {selectedVideo.category_tags.map((tag) => (
                    <span key={tag.id} className="pill muted">#{tag.name}</span>
                  ))}
                </div>

                <p style={{ marginTop: '16px', lineHeight: '1.6' }}>{selectedVideo.description || "无简介"}</p>
              </div>
            )}
          </section>

          <aside className="video-play-sidebar panel">
            <div className="section-head compact-head">
              <div>
                <p className="eyebrow">视频管理</p>
                <h2>操作</h2>
              </div>
            </div>
            
            {selectedVideo && (
              <div className="detail-copy">
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
                <p><strong>原始格式:</strong> {formatCodecs(selectedVideo.original_video_codec, selectedVideo.original_audio_codec)}</p>
                <p><strong>播放格式:</strong> {formatCodecs(selectedVideo.video_codec, selectedVideo.audio_codec)}</p>
                <p><strong>画面:</strong> {formatResolution(selectedVideo.width, selectedVideo.height)} · {formatDurationSeconds(selectedVideo.duration_seconds)}</p>
                <p>
                  {selectedVideo.faststart_applied ? "· 已完成 faststart 优化" : "· 未优化"}
                </p>
                {selectedVideo.processing_error && <p style={{color: 'red'}}>优化错误：{selectedVideo.processing_error}</p>}
                
                <button 
                  className="danger-button" 
                  style={{ marginTop: '20px', width: '100%', background: '#ff3b30', color: '#fff', border: 'none', padding: '10px', borderRadius: '4px', cursor: 'pointer' }}
                  disabled={busy} 
                  onClick={() => {
                    if (confirm("确定要删除此视频吗？")) {
                      void handleDeleteCurrentVideo().then(() => {
                        window.close(); // Optional: close tab on delete
                      });
                    }
                  }}
                >
                  删除视频
                </button>
              </div>
            )}
          </aside>
        </main>
      )}


            {page === "gallery" && (
        <main className="page-grid gallery-page">
          <section className="panel filter-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">筛选器</p>
                <h2>人物 + 自定义标签</h2>
              </div>
              <span>组内 OR，组间 AND</span>
            </div>

            <div className="filter-group">
              <label>按人物筛选</label>
              <input
                className="search-input subtle"
                value={personSearch}
                onChange={(event) => setPersonSearch(event.target.value)}
                placeholder="搜索人物名"
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
                        <img src={`${photo.thumbnail_url}?width=720`} alt="图库预览" loading="lazy" />
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
                        <img src={`${photo.thumbnail_url}?width=720`} alt="图库预览" loading="lazy" />
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

          <aside className="panel detail-panel">
            <div className="section-head">
              <div>
                <p className="eyebrow">详情</p>
                <h2>单张图修正</h2>
              </div>
              <div className="micro-row">
                <span>{selectedPhoto ? `${selectedPhoto.faces.length} 张脸` : "未选中图片"}</span>
                <button disabled={busy || !selectedPhoto} onClick={() => void handleReRecognize()}>
                  重新识别
                </button>
                <button disabled={busy || !selectedPhoto} onClick={() => void handleDeleteCurrentPhoto()}>
                  删除当前图
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
                  <p>{formatDate(selectedPhoto.taken_at || selectedPhoto.created_at)}</p>
                  <p>
                    {selectedPhoto.width} × {selectedPhoto.height}
                  </p>
                </div>

                <div className="editor-block">
                  <label>人物标签</label>
                  <div className="micro-row wrap">
                    {selectedPhoto.persons.map((person) => (
                      <button
                        key={person.person_id}
                        className={person.is_unknown ? "pill unknown action-pill" : "pill action-pill"}
                        onClick={() => void handleDeletePhotoPerson(person.person_id)}
                      >
                        {person.person_name}
                      </button>
                    ))}
                  </div>
                  <div className="inline-editor inline-editor-triple">
                    <select value={manualPersonId} onChange={(event) => setManualPersonId(event.target.value)}>
                      <option value="">选择人物添加到当前图片</option>
                      {availablePersonsForPhoto.map((person) => (
                        <option key={person.id} value={person.id}>
                          {person.display_name}
                        </option>
                      ))}
                    </select>
                    <button disabled={busy || !manualPersonId} onClick={() => void handleAddPhotoPerson()}>
                      添加人物
                    </button>
                  </div>
                  {selectedPhoto.faces.length !== 1 && <p className="tip">多人图只改展示标签，不自动写入人物向量库。</p>}
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
                    <div className="inline-editor">
                      <select value={manualTagId} onChange={(event) => setManualTagId(event.target.value)}>
                        <option value="">选择已有标签</option>
                        {availableTagsForPhoto.map((tag) => (
                          <option key={tag.id} value={tag.id}>
                            #{tag.name}
                          </option>
                        ))}
                      </select>
                      <button disabled={busy || !manualTagId} onClick={() => void handleAddPhotoTag()}>
                        添加已有标签
                      </button>
                    </div>
                    <div className="inline-editor">
                      <input
                        value={manualTagName}
                        onChange={(event) => setManualTagName(event.target.value)}
                        placeholder="输入新标签名称"
                      />
                      <button disabled={busy || !manualTagName.trim()} onClick={() => void handleAddPhotoTag()}>
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
                      <span>{face.match_score ? `score ${face.match_score.toFixed(3)}` : "无匹配分数"}</span>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-card">从左侧图库点击任意图片后，这里会显示识别结果和修正操作。</div>
            )}
          </aside>
        </main>
      )}

      {page === "people" && (
        <main className="page-grid people-page">
          <section className="panel people-sidebar">
            <div className="section-head">
              <div>
                <p className="eyebrow">人物库</p>
                <h2>创建与选择人物</h2>
              </div>
              <div className="micro-row section-actions">
                <span>{persons.length} 人</span>
                <button disabled={busy} onClick={() => togglePeopleBatchDeleteMode()}>
                  {peopleBatchDeleteMode ? "取消批量" : "批量删除"}
                </button>
                <button
                  disabled={busy || !peopleBatchDeleteMode || selectedPersonDeleteIds.length === 0}
                  onClick={() => void handleDeleteSelectedPersons()}
                >
                  删除选中（{selectedPersonDeleteIds.length}）
                </button>
                <button disabled={busy || orphanUnknownCount === 0} onClick={() => void handleDeleteAllUnknownPersons()}>
                  清空无关联未知人物（{orphanUnknownCount}）
                </button>
                <button disabled={busy || unknownPersonCount === 0} onClick={() => void handleReRecognizeAllUnknownPhotos()}>
                  一键重新识别所有未知人物
                </button>
                <button disabled={busy} onClick={handleExportPersons}>
                  导出样本库
                </button>
                <button disabled={busy} onClick={handlePickImportFile}>
                  导入样本库
                </button>
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
            </div>

            <div className="inline-editor">
              <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} placeholder="输入新人物名称" />
              <button disabled={busy || !newPersonName.trim()} onClick={() => void handleCreatePerson()}>
                创建人物
              </button>
            </div>

            <input
              className="search-input subtle"
              value={peopleSearch}
              onChange={(event) => setPeopleSearch(event.target.value)}
              placeholder="搜索人物（样本库）"
            />

            <div className="person-list">
              {filteredPeopleInLibrary.map((person) => (
                <article key={person.id} className="person-card-wrap">
                  <button
                    className={selectedPerson?.id === person.id ? "person-card active" : "person-card"}
                    onClick={() => handleSelectPerson(person)}
                  >
                    <div>
                      <strong>{person.display_name}</strong>
                      <span>{person.is_unknown ? "未知人物" : "正式人物"}</span>
                    </div>
                    <small>
                      样本 {person.sample_count} · 图库 {person.gallery_photo_count}
                    </small>
                  </button>
                  {peopleBatchDeleteMode && (
                    <label className="row-check">
                      <input
                        type="checkbox"
                        checked={selectedPersonDeleteIds.includes(person.id)}
                        onChange={(event) => {
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
                    <span>{selectedPerson.is_unknown ? "可直接改名转正" : "样本库维护"}</span>
                    <button disabled={busy} onClick={() => void handleDeleteCurrentPerson()}>
                      删除当前人物
                    </button>
                  </div>
                </div>

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

                {pendingSampleUploads.length > 0 && (
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
                          <img src={`${sample.thumbnail_url}?width=480`} alt="样本缩略图" />
                        </a>
                        <div className="sample-copy">
                          <strong>样本记录 #{sample.id}</strong>
                          <span>{formatDate(sample.taken_at || sample.created_at)}</span>
                          <small className={`status-pill status-${sample.status}`}>{sample.status}</small>
                          {sample.error_message && <p>{sample.error_message}</p>}
                        </div>
                        <button className="ghost-button" onClick={() => void handleDeleteSample(sample.id)}>
                          删除样本
                        </button>
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
      )}

      {page === "upload" && (
        <main className="page-grid upload-page">
          <section className="panel upload-main">
            <div className="section-head">
              <div>
                <p className="eyebrow">展示图上传</p>
                <h2>自动识别并打标签</h2>
              </div>
              <span>支持批量导入</span>
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
              <small className="tip">
                {uploadMode === "rich"
                  ? `将自动打 #图文 标签${richTag ? "" : "（系统会自动创建）"}，并执行 OCR + 人脸识别`
                  : "沿用普通图片流程：人脸识别 + 人物标签 + 普通标签"}
              </small>
            </div>

            <label className="upload-box large">
              <input type="file" multiple accept="image/*" onChange={(event) => handlePickGalleryFiles(event.target.files)} />
              <strong>{uploadMode === "rich" ? "拖入或选择图文图片" : "拖入或选择展示图片"}</strong>
              <span>
                {uploadMode === "rich"
                  ? "先预览并补录文本（可留空走 OCR），确认后再统一上传。"
                  : "先预览并填写每张图的人物和标签，确认后再统一上传到后端识别。"}
              </span>
            </label>

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
                    <button disabled={busy} onClick={() => handleApplyBatchMetadataToAll()}>
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
                <button disabled={busy} onClick={() => void handleConfirmGalleryUpload()}>
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
                <span>自动生成 `未知人物-0001` 这类实体，后续可在人物样本库页直接改名转正。</span>
              </article>
              <article>
                <strong>普通标签</strong>
                <span>支持选已有，也支持上传时现场新增，供页面 A 组合检索。</span>
              </article>
            </div>
          </aside>
        </main>
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
        <div className="lightbox-backdrop" onClick={() => closeGalleryLightbox()}>
          <div className={lightboxPhoto.is_rich_text ? "lightbox-shell rich-lightbox" : "lightbox-shell"} onClick={(event) => event.stopPropagation()}>
            <button className="lightbox-close" onClick={() => closeGalleryLightbox()}>
              关闭
            </button>
            <button className="lightbox-arrow left" disabled={!canGoPrev || busy} onClick={() => void goPrevLightbox()}>
              {isFirstOfPage && hasPrevPage ? (
                <>
                  ‹ <span>上一页</span>
                </>
              ) : (
                "‹"
              )}
            </button>
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
            <button className="lightbox-arrow right" disabled={!canGoNext || busy} onClick={() => void goNextLightbox()}>
              {isLastOfPage && hasNextPage ? (
                <>
                  <span>下一页</span> ›
                </>
              ) : (
                "›"
              )}
            </button>
          </div>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}
