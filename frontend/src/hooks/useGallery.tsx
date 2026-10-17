import MediaSource from "../components/MediaSource";
import { Info } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import {
  addGalleryPhotoPerson,
  addGalleryPhotoTag,
  batchDeleteGalleryPhotos,
  bindGalleryFacePerson,
  deleteGalleryPhoto,
  deleteGalleryPhotoPerson,
  deleteGalleryPhotoTag,
  downloadGalleryExport,
  getGalleryPhoto,
  getTask,
  importGalleryExportZip,
  listGalleryPhotos,
  promoteGalleryFaceSample,
  promoteGalleryPhotoPersonSample,
  reRecognizeGalleryPhoto,
  undoGalleryPhotoPersonSample,
  unbindGalleryFacePerson,
  updateGalleryPhotoRichText,
  type GalleryExportScope
} from "../api";
import type { ConfirmDialogOptions } from "../components/ConfirmDialog";
import { formatError } from "../lib/formatError";
import { parseGalleryPhotoIdQuery, resolveActivePhotoIdSearch } from "../lib/galleryPhotoIdSearch";
import { useDebounce } from "./useDebounce";
import {
  deselectGalleryPage,
  isGalleryPageSelected,
  selectGalleryPage,
  selectGalleryPhotoRange,
  toggleGalleryPhotoSelection
} from "../lib/gallerySelection";
import { availablePhotoPersons, filterPersonMatches, resolveExistingPerson } from "../lib/personPicker";
import { isCurrentRequest, nextRequestId } from "../lib/requestGeneration";
import type { PageKey } from "../lib/routing";
import { sortByPinyin, sortByPinyinName } from "../lib/sort";
import { filterTagMatches, resolveExistingTag } from "../lib/tagPicker";
import { isTerminalTask } from "../lib/taskStatus";
import type { GalleryPhotoDetail, GalleryPhotoListItem, Person, Tag, Task } from "../types";
import { usePolling } from "./usePolling";
import { useGalleryLightbox } from "./useGalleryLightbox";

export const galleryPageSize = 20;
const compactGalleryMediaQuery = "(max-width: 1600px)";

export type GalleryDrawer = "detail" | null;
export type GalleryFilterSection = "include-people" | "include-tags" | "exclude-people" | "exclude-tags";
export type GalleryDetailTab = "people" | "tags" | "faces" | "rich-text";

type UseGalleryOptions = {
  persons: Person[];
  tags: Tag[];
  page: PageKey;
  workspaceId: number;
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  refreshPeople: () => Promise<Person[]>;
  refreshTags: () => Promise<unknown>;
  canAddGallery: boolean;
  canDeleteGallery: boolean;
  canEditGallery: boolean;
  onOpenMatchedSample: (personId: number, samplePhotoId: number) => void;
};

export function useGallery({
  persons,
  tags,
  page,
  workspaceId,
  confirm,
  refreshPeople,
  refreshTags,
  canAddGallery,
  canDeleteGallery,
  canEditGallery,
  onOpenMatchedSample
}: UseGalleryOptions) {
  const [galleryPhotos, setGalleryPhotos] = useState<GalleryPhotoListItem[]>([]);
  const [galleryTotal, setGalleryTotal] = useState(0);
  const [galleryOffset, setGalleryOffset] = useState(0);
  const [gallerySelectionMode, setGallerySelectionMode] = useState(false);
  const [selectedGalleryPhotoIds, setSelectedGalleryPhotoIds] = useState<number[]>([]);
  const [lastSelectedGalleryPhotoId, setLastSelectedGalleryPhotoId] = useState<number | null>(null);
  const [galleryExportModalOpen, setGalleryExportModalOpen] = useState(false);
  const [galleryExportScope, setGalleryExportScope] = useState<GalleryExportScope>("filtered");
  const [galleryExportPersonIds, setGalleryExportPersonIds] = useState<number[]>([]);
  const [galleryExportTagIds, setGalleryExportTagIds] = useState<number[]>([]);
  const [galleryExportExcludePersonIds, setGalleryExportExcludePersonIds] = useState<number[]>([]);
  const [galleryExportExcludeTagIds, setGalleryExportExcludeTagIds] = useState<number[]>([]);
  const [galleryExportStartPhotoId, setGalleryExportStartPhotoId] = useState<number | null>(null);
  const [selectedPersonIds, setSelectedPersonIds] = useState<number[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [excludePersonIds, setExcludePersonIds] = useState<number[]>([]);
  const [excludeTagIds, setExcludeTagIds] = useState<number[]>([]);
  const [personSearch, setPersonSearch] = useState("");
  const [tagSearch, setTagSearch] = useState("");

  const richTag = useMemo(() => tags.find((tag) => tag.name === "图文") ?? null, [tags]);
  const normalTags = useMemo(() => sortByPinyinName(tags.filter((tag) => !tag.is_system)), [tags]);
  const filteredPersons = useMemo(
    () => filterPersonMatches(persons, personSearch),
    [personSearch, persons]
  );
  const allFilteredUnknownPersons = useMemo(
    () => filteredPersons.filter((person) => person.is_unknown),
    [filteredPersons]
  );
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
    () => sortByPinyin(persons.filter((person) => excludePersonIds.includes(person.id)), (person) => person.display_name),
    [persons, excludePersonIds]
  );
  const excludedFilterTags = useMemo(
    () => tags.filter((tag) => excludeTagIds.includes(tag.id)),
    [tags, excludeTagIds]
  );
  const availableExcludePersons = useMemo(
    () =>
      sortByPinyin(
        persons.filter((person) => !selectedPersonIds.includes(person.id) && !excludePersonIds.includes(person.id)),
        (person) => person.display_name
      ),
    [persons, selectedPersonIds, excludePersonIds]
  );
  const availableExcludeTags = useMemo(
    () => sortByPinyinName(tags.filter((tag) => !selectedTagIds.includes(tag.id) && !excludeTagIds.includes(tag.id))),
    [tags, selectedTagIds, excludeTagIds]
  );

  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [selectedPhoto, setSelectedPhoto] = useState<GalleryPhotoDetail | null>(null);
  const [galleryDrawer, setGalleryDrawer] = useState<GalleryDrawer>(null);
  const [galleryCompact, setGalleryCompact] = useState(() => window.matchMedia(compactGalleryMediaQuery).matches);
  const [activeGalleryFilterSection, setActiveGalleryFilterSection] = useState<GalleryFilterSection | null>("include-people");
  const [galleryFiltersExpanded, setGalleryFiltersExpanded] = useState(true);
  const [galleryDetailPinned, setGalleryDetailPinned] = useState(false);
  const [activeGalleryDetailTab, setActiveGalleryDetailTab] = useState<GalleryDetailTab>("people");
  const [selectedFaceId, setSelectedFaceId] = useState<number | null>(null);
  const [excludePersonSearch, setExcludePersonSearch] = useState("");
  const [excludeTagSearch, setExcludeTagSearch] = useState("");
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
  const [galleryImportTask, setGalleryImportTask] = useState<Task | null>(null);
  const [jumpPageInput, setJumpPageInput] = useState("");
  const [recognitionNotice, setRecognitionNotice] = useState<{ id: number; message: string } | null>(null);
  const galleryImportFileRef = useRef<HTMLInputElement | null>(null);
  const galleryDetailRef = useRef<HTMLElement | null>(null);
  const galleryDetailCloseRef = useRef<HTMLButtonElement | null>(null);
  const galleryDrawerReturnFocusRef = useRef<HTMLElement | null>(null);
  const galleryRequestIdRef = useRef(0);
  const [photoIdSearchInput, setPhotoIdSearchInput] = useState("");
  const [activePhotoIdSearch, setActivePhotoIdSearch] = useState<number | null>(null);
  const activePhotoIdSearchRef = useRef<number | null>(null);
  const debouncedPhotoIdSearchInput = useDebounce(photoIdSearchInput, 300);
  const photoIdSearchQuery = useMemo(() => parseGalleryPhotoIdQuery(photoIdSearchInput), [photoIdSearchInput]);
  const photoIdSearchHint = photoIdSearchQuery.kind === "invalid" ? photoIdSearchQuery.message : null;
  const unknownPersonCount = useMemo(() => persons.filter((person) => person.is_unknown).length, [persons]);
  const galleryFilterCount = selectedPersonIds.length + selectedTagIds.length + excludePersonIds.length + excludeTagIds.length;
  const includedKnownPersons = useMemo(
    () => filteredPersons.filter((person) => !person.is_unknown),
    [filteredPersons]
  );
  const includedUnknownPersons = useMemo(
    () => filteredPersons.filter((person) => person.is_unknown),
    [filteredPersons]
  );
  const excludedPersonResults = useMemo(
    () => filterPersonMatches([...excludedFilterPersons, ...availableExcludePersons], excludePersonSearch),
    [availableExcludePersons, excludePersonSearch, excludedFilterPersons]
  );
  const excludedKnownPersonResults = useMemo(
    () => excludedPersonResults.filter((person) => !person.is_unknown),
    [excludedPersonResults]
  );
  const excludedUnknownPersonResults = useMemo(
    () => excludedPersonResults.filter((person) => person.is_unknown),
    [excludedPersonResults]
  );
  const excludedTagResults = useMemo(
    () => filterTagMatches(sortByPinyinName([...excludedFilterTags, ...availableExcludeTags]), excludeTagSearch),
    [availableExcludeTags, excludeTagSearch, excludedFilterTags]
  );
  // 编号搜索生效时忽略人物/标签筛选（但不清空筛选状态），清除搜索后原筛选自动恢复。
  function listGalleryPhotosWithSearch(
    personIds: number[],
    tagIds: number[],
    epIds: number[],
    etIds: number[],
    nextOffset: number,
  ) {
    const photoId = activePhotoIdSearchRef.current;
    if (photoId != null) {
      return listGalleryPhotos([], [], [], [], nextOffset, galleryPageSize, photoId);
    }
    return listGalleryPhotos(personIds, tagIds, epIds, etIds, nextOffset, galleryPageSize);
  }

  function applyPhotoIdSearch(photoId: number | null) {
    if (activePhotoIdSearchRef.current === photoId) {
      return;
    }
    activePhotoIdSearchRef.current = photoId;
    setActivePhotoIdSearch(photoId);
    setSelectedGalleryPhotoIds([]);
    refreshGallery(0).catch((cause: unknown) => {
      setError(formatError(cause, "按编号搜索图片失败。"));
    });
  }

  useEffect(() => {
    // 非法输入同样清除已生效的编号搜索，保证列表、标签与导出始终与输入框一致。
    applyPhotoIdSearch(resolveActivePhotoIdSearch(parseGalleryPhotoIdQuery(debouncedPhotoIdSearchInput)));
  }, [debouncedPhotoIdSearchInput]);

  function handleClearPhotoIdSearch() {
    setPhotoIdSearchInput("");
    applyPhotoIdSearch(null);
  }

  async function refreshGallery(
    nextOffset = galleryOffset,
    personIds = selectedPersonIds,
    tagIds = selectedTagIds,
    nextExcludePersonIds?: number[],
    nextExcludeTagIds?: number[],
  ) {
    lightbox.cancelNavigation();
    const epIds = nextExcludePersonIds ?? excludePersonIds;
    const etIds = nextExcludeTagIds ?? excludeTagIds;
    const requestId = nextRequestId(galleryRequestIdRef);
    const response = await listGalleryPhotosWithSearch(personIds, tagIds, epIds, etIds, nextOffset);
    if (!isCurrentRequest(galleryRequestIdRef, requestId)) {
      return;
    }
    setGalleryPhotos(response.items);
    setGalleryTotal(response.total);
    setGalleryOffset(response.offset);
  }
  function openGalleryDrawer(nextDrawer: Exclude<GalleryDrawer, null>) {
    const activeElement = document.activeElement;
    if (activeElement instanceof HTMLElement && activeElement !== document.body) {
      galleryDrawerReturnFocusRef.current = activeElement;
    }
    setGalleryDrawer(nextDrawer);
  }

  function closeGalleryDrawer(restoreFocus = true) {
    setGalleryDrawer(null);
    setGalleryDetailPinned(false);
    if (!restoreFocus) {
      return;
    }
    window.requestAnimationFrame(() => {
      const returnTarget = galleryDrawerReturnFocusRef.current;
      galleryDrawerReturnFocusRef.current = null;
      if (returnTarget?.isConnected) {
        returnTarget.focus();
      }
    });
  }

  useEffect(() => {
    const mediaQuery = window.matchMedia(compactGalleryMediaQuery);
    const handleChange = () => {
      setGalleryCompact(mediaQuery.matches);
      if (mediaQuery.matches) {
        setGalleryDetailPinned(false);
      }
    };
    handleChange();
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    if (page !== "gallery") {
      setGalleryDrawer(null);
      setGalleryDetailPinned(false);
    }
  }, [page]);

  useEffect(() => {
    setSelectedGalleryPhotoIds([]);
    setGallerySelectionMode(false);
    setGalleryExportModalOpen(false);
    setGalleryExportStartPhotoId(null);
    setGalleryDetailPinned(false);
  }, [
    workspaceId,
    setGalleryExportModalOpen,
    setGalleryExportStartPhotoId,
    setGallerySelectionMode,
    setSelectedGalleryPhotoIds
  ]);

  useEffect(() => {
    galleryDetailRef.current?.toggleAttribute("inert", galleryCompact && galleryDrawer !== "detail");
  }, [galleryCompact, galleryDrawer, page]);

  useEffect(() => {
    if (!galleryCompact || !galleryDrawer) {
      return undefined;
    }

    const previousOverflow = document.body.style.overflow;
    const panel = galleryDetailRef.current;
    const closeButton = galleryDetailCloseRef.current;
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
    setSelectedGalleryPhotoIds([]);
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

  function handleToggleTagFilter(tagId: number) {
    setSelectedGalleryPhotoIds([]);
    const active = selectedTagIds.includes(tagId);
    const next = active ? selectedTagIds.filter((id) => id !== tagId) : [...selectedTagIds, tagId];
    setSelectedTagIds(next);
    let nextExclude = excludeTagIds;
    if (!active && excludeTagIds.includes(tagId)) {
      nextExclude = excludeTagIds.filter((id) => id !== tagId);
      setExcludeTagIds(nextExclude);
    }
    void refreshGallery(0, selectedPersonIds, next, excludePersonIds, nextExclude);
  }

  function handleToggleUnknownPersonFilters() {
    const targetIds = allFilteredUnknownPersons.map((person) => person.id);
    if (targetIds.length === 0) {
      return;
    }
    setSelectedGalleryPhotoIds([]);
    const targetIdSet = new Set(targetIds);
    const next = allFilteredUnknownSelected
      ? selectedPersonIds.filter((id) => !targetIdSet.has(id))
      : Array.from(new Set([...selectedPersonIds, ...targetIds]));
    setSelectedPersonIds(next);
    let nextExclude = excludePersonIds;
    if (!allFilteredUnknownSelected) {
      nextExclude = excludePersonIds.filter((id) => !targetIdSet.has(id));
      setExcludePersonIds(nextExclude);
    }
    void refreshGallery(0, next, selectedTagIds, nextExclude, excludeTagIds);
  }

  function handleClearGalleryFilters() {
    if (galleryFilterCount === 0 && activePhotoIdSearch == null) {
      return;
    }
    setPhotoIdSearchInput("");
    activePhotoIdSearchRef.current = null;
    setActivePhotoIdSearch(null);
    setSelectedGalleryPhotoIds([]);
    setSelectedPersonIds([]);
    setSelectedTagIds([]);
    setExcludePersonIds([]);
    setExcludeTagIds([]);
    void refreshGallery(0, [], [], [], []);
  }

  function toggleGalleryFilterSection(section: GalleryFilterSection) {
    setActiveGalleryFilterSection(section);
  }

  function handleToggleExcludePerson(personId: number) {
    setSelectedGalleryPhotoIds([]);
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
    setSelectedGalleryPhotoIds([]);
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
    const timer = window.setTimeout(() => setRecognitionNotice(null), 2000);
    return () => window.clearTimeout(timer);
  }, [recognitionNotice]);
  useEffect(() => {
    void (async () => {
      try {
        await refreshGallery(0, [], []);
      } catch (cause) {
        setError(formatError(cause, "初始化图库失败。"));
      }
    })();
  }, []);

  usePolling(
    async () => {
      if (!galleryImportTask || isTerminalTask(galleryImportTask)) {
        return;
      }
      try {
        const nextTask = await getTask(galleryImportTask.id);
        setGalleryImportTask(nextTask);
        if (nextTask.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
          setBusy(false);
        }
        if (nextTask.status === "failed" || nextTask.status === "canceled") {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "展示图 ZIP 导入轮询失败。");
        setBusy(false);
      }
    },
    1500,
    Boolean(galleryImportTask && !isTerminalTask(galleryImportTask))
  );

  async function openGalleryPhoto(photoId: number) {
    setError(null);
    try {
      const detail = await getGalleryPhoto(photoId);
      setSelectedPhoto(detail);
      setActiveGalleryDetailTab((current) => current === "rich-text" && !detail.is_rich_text ? "people" : current);
      setRichTextDraft(detail.rich_text ?? "");
      setManualPersonId("");
      setManualPersonSearch("");
      setManualPersonNotice(null);
      setManualTagId("");
      setManualTagSearch("");
      setManualTagNotice(null);
      setManualTagName("");
      setSelectedFaceId(null);
      openGalleryDrawer("detail");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加载图片详情失败。");
    }
  }

  function openGalleryLightbox(photoId: number, visualOrder: readonly number[]) {
    closeGalleryDrawer(false);
    setGalleryDetailPinned(false);
    lightbox.open(photoId, visualOrder);
  }

  function closeGalleryLightbox() {
    lightbox.close();
    setLightboxEditMode(false);
  }
  async function openLightboxPhotoDetail() {
    if (!lightboxPhoto) {
      return;
    }
    const photoId = lightboxPhoto.id;
    closeGalleryLightbox();
    await openGalleryPhoto(photoId);
  }
  function copyCurrentGalleryFiltersToExport() {
    setGalleryExportPersonIds(selectedPersonIds);
    setGalleryExportTagIds(selectedTagIds.filter((tagId) => tags.some((tag) => tag.id === tagId && !tag.is_system)));
    setGalleryExportExcludePersonIds(excludePersonIds);
    setGalleryExportExcludeTagIds(excludeTagIds);
  }

  function openGalleryExportModal() {
    setGalleryExportScope("filtered");
    setGalleryExportStartPhotoId(null);
    copyCurrentGalleryFiltersToExport();
    setGalleryExportModalOpen(true);
  }

  function openSelectedGalleryExportModal() {
    if (selectedGalleryPhotoIds.length === 0) {
      return;
    }
    setGalleryExportScope("selected");
    setGalleryExportStartPhotoId(null);
    copyCurrentGalleryFiltersToExport();
    setGalleryExportModalOpen(true);
  }

  function openGalleryExportFromPhoto(photoId: number) {
    setGalleryExportScope("from_start");
    setGalleryExportStartPhotoId(photoId);
    copyCurrentGalleryFiltersToExport();
    setGalleryExportModalOpen(true);
  }

  async function handleExportGalleryPhotos() {
    setBusy(true);
    setError(null);
    try {
      const exportPhotoId =
        activePhotoIdSearch != null && (galleryExportScope === "filtered" || galleryExportScope === "from_start")
          ? activePhotoIdSearch
          : undefined;
      const { blob, filename } = await downloadGalleryExport({
        scope: galleryExportScope,
        photoIds: galleryExportScope === "selected" ? selectedGalleryPhotoIds : undefined,
        // 编号搜索时结果只有被搜索的那一张，起点自动对齐到该图片，避免“起点不在当前筛选结果中”。
        startPhotoId:
          galleryExportScope === "from_start" ? exportPhotoId ?? galleryExportStartPhotoId ?? undefined : undefined,
        personIds: exportPhotoId != null ? [] : galleryExportPersonIds,
        tagIds: exportPhotoId != null ? [] : galleryExportTagIds,
        excludePersonIds: exportPhotoId != null ? [] : galleryExportExcludePersonIds,
        excludeTagIds: exportPhotoId != null ? [] : galleryExportExcludeTagIds,
        photoId: exportPhotoId
      });
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
      setGalleryExportModalOpen(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导出展示图失败。");
    } finally {
      setBusy(false);
    }
  }

  function handleToggleGalleryExportPerson(personId: number) {
    setGalleryExportPersonIds((current) =>
      current.includes(personId) ? current.filter((id) => id !== personId) : [...current, personId]
    );
  }

  function handleToggleGalleryExportTag(tagId: number) {
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
      if (isTerminalTask(task)) {
        if (task.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
        }
        setBusy(false);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "展示图 ZIP 导入失败。");
      setBusy(false);
    }
    if (event.target) {
      event.target.value = "";
    }
  }
  function renderFaceMatchSource(
    personId: number,
    source: "sample" | "centroid" | null,
    samplePhotoId: number | null,
  ) {
    if (source === "sample") {
      return samplePhotoId !== null ? (
        <button
          type="button"
          className="matched-sample-link"
          onClick={() => onOpenMatchedSample(personId, samplePhotoId)}
        >
          命中样本 #{samplePhotoId}
        </button>
      ) : <span>命中样本已删除</span>;
    }
    if (source === "centroid") {
      return <span>人物中心向量</span>;
    }
    return <span>历史记录未保存来源，请重新识别</span>;
  }

  function faceRejectionReasonLabel(reason: string): string {
    return {
      no_candidate: "没有候选人物",
      candidate_not_found: "候选人物不存在",
      below_threshold: "第一候选低于阈值",
      insufficient_margin: "前两名差值不足",
    }[reason] ?? reason;
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

  async function handleBindFace(faceId: number, personId: number) {
    if (!selectedPhoto) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await bindGalleryFacePerson(selectedPhoto.id, faceId, personId);
      setSelectedPhoto(detail);
      setSelectedFaceId(faceId);
      setManualPersonId("");
      setManualPersonSearch("");
      setManualPersonNotice(null);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "绑定人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handlePromoteFace(faceId: number) {
    if (!selectedPhoto) return;
    setBusy(true);
    setError(null);
    try {
      const detail = await promoteGalleryFaceSample(selectedPhoto.id, faceId);
      setSelectedPhoto(detail);
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "加入样本库失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleUnbindFace(faceId: number, requireConfirmation = true) {
    if (!selectedPhoto) return;
    if (requireConfirmation && !await confirm({ title: "解除人脸绑定", message: "确定将这张脸恢复为待确认状态吗？", confirmLabel: "解除绑定", tone: "danger" })) return;
    setBusy(true);
    setError(null);
    try {
      setSelectedPhoto(await unbindGalleryFacePerson(selectedPhoto.id, faceId));
      await Promise.all([refreshPeople(), refreshGallery(galleryOffset, selectedPersonIds, selectedTagIds)]);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "解除绑定失败。");
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
        setLastSelectedGalleryPhotoId(null);
      }
      return !current;
    });
  }

  function handleGalleryCardClick(photoId: number, shiftKey: boolean, visualPageIds?: number[], lightboxPageIds?: number[]) {
    // Shift 保持列优先范围选择；灯箱使用另外采集的横向阅读顺序。
    const pageIds = visualPageIds ?? galleryPhotos.map((photo) => photo.id);
    if (shiftKey) {
      if (!gallerySelectionMode) {
        setGallerySelectionMode(true);
      }
      setSelectedGalleryPhotoIds((current) =>
        selectGalleryPhotoRange(current, pageIds, lastSelectedGalleryPhotoId, photoId)
      );
      setLastSelectedGalleryPhotoId(photoId);
      return;
    }

    if (gallerySelectionMode) {
      setSelectedGalleryPhotoIds((current) => toggleGalleryPhotoSelection(current, photoId));
      setLastSelectedGalleryPhotoId(photoId);
      return;
    }

    openGalleryLightbox(photoId, lightboxPageIds ?? []);
  }

  function handleGalleryCheckboxClick(photoId: number, shiftKey: boolean, visualPageIds?: number[]) {
    const pageIds = visualPageIds ?? galleryPhotos.map((photo) => photo.id);
    if (shiftKey) {
      if (!gallerySelectionMode) {
        setGallerySelectionMode(true);
      }
      setSelectedGalleryPhotoIds((current) =>
        selectGalleryPhotoRange(current, pageIds, lastSelectedGalleryPhotoId, photoId)
      );
      setLastSelectedGalleryPhotoId(photoId);
    } else {
      setSelectedGalleryPhotoIds((current) => toggleGalleryPhotoSelection(current, photoId));
      setLastSelectedGalleryPhotoId(photoId);
    }
  }

  function toggleCurrentGalleryPageSelection() {
    const pageIds = galleryPhotos.map((photo) => photo.id);
    setSelectedGalleryPhotoIds((current) =>
      isGalleryPageSelected(current, pageIds)
        ? deselectGalleryPage(current, pageIds)
        : selectGalleryPage(current, pageIds)
    );
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
  const galleryExportStartIndex = galleryExportStartPhotoId === null
    ? -1
    : galleryPhotos.findIndex((photo) => photo.id === galleryExportStartPhotoId);
  const galleryExportStartCount = galleryExportStartIndex < 0
    ? 0
    : galleryOffset + galleryExportStartIndex + 1;
  const galleryExportFiltersDisabled =
    galleryExportScope === "all" ||
    galleryExportScope === "selected" ||
    galleryExportScope === "from_start";
  const galleryExportDisabled =
    busy ||
    (galleryExportScope === "selected" && selectedGalleryPhotoIds.length === 0) ||
    (galleryExportScope === "from_start" && galleryExportStartPhotoId === null);

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

  const lightbox = useGalleryLightbox({
    photos: galleryPhotos,
    offset: galleryOffset,
    total: galleryTotal,
    pageSize: galleryPageSize,
    contextKey: JSON.stringify([page, workspaceId, selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds, activePhotoIdSearch]),
    busy,
    loadPage: async (offset) => {
      const requestId = nextRequestId(galleryRequestIdRef);
      const response = await listGalleryPhotosWithSearch(selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds, offset);
      return isCurrentRequest(galleryRequestIdRef, requestId) ? response : null;
    },
    commitPage: (response) => {
      setGalleryPhotos(response.items);
      setGalleryTotal(response.total);
      setGalleryOffset(response.offset);
      setSelectedGalleryPhotoIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
    },
    onError: setError,
  });
  const {
    photo: lightboxPhoto, index: lightboxIndex,
    isFirstOfPage, isLastOfPage, hasPrevPage, hasNextPage, canGoPrev, canGoNext,
    goPrevious: goPrevLightbox, goNext: goNextLightbox,
    navigating: lightboxNavigating, layoutRequest: lightboxLayoutRequest, completeLayout: completeLightboxLayout,
  } = lightbox;

  useEffect(() => {
    if (lightboxPhoto && lightboxPhoto.is_rich_text) {
      setLightboxRichTextDraft(lightboxPhoto.rich_text || "");
    } else if (!lightboxPhoto) {
      setLightboxEditMode(false);
    }
  }, [lightboxPhoto]);

  const lightboxMeta = lightboxPhoto ? (
    <>
      <MediaSource mediaType="photo" mediaId={lightboxPhoto.id} summary={lightboxPhoto.source_summary} />
      <div className="lightbox-meta-head">
        <span className="lightbox-photo-id">#{lightboxPhoto.id}</span>
        <strong>{lightboxIndex >= 0 ? `${lightbox.offset + lightboxIndex + 1} / ${lightbox.total}` : "图片信息"}</strong>
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
      <button className="lightbox-detail-button" disabled={busy || lightboxNavigating} onClick={() => void openLightboxPhotoDetail()}>
        <Info size={16} aria-hidden="true" />
        查看详情
      </button>
    </>
  ) : null;

  return {
    error, setError, busy, canAddGallery, canDeleteGallery, canEditGallery,
    galleryPhotos, galleryTotal, galleryOffset, galleryPageSize, gallerySelectionMode, selectedGalleryPhotoIds,
    lastSelectedGalleryPhotoId, selectedPersonIds, selectedTagIds, excludePersonIds, excludeTagIds,
    personSearch, tagSearch, richTag, normalTags, filteredPersons, allFilteredUnknownPersons, allFilteredUnknownSelected,
    filteredTags, excludedFilterPersons, excludedFilterTags, availableExcludePersons, availableExcludeTags,
    selectedPhoto, galleryDrawer, galleryCompact, activeGalleryFilterSection, galleryFiltersExpanded, galleryDetailPinned,
    activeGalleryDetailTab, selectedFaceId, excludePersonSearch, excludeTagSearch, manualPersonId, manualPersonSearch,
    manualPersonNotice, manualTagId, manualTagSearch, manualTagNotice, manualTagName, richTextDraft, lightboxRichTextDraft,
    lightboxEditMode, galleryImportFileRef, galleryImportTask, jumpPageInput, galleryDetailRef, galleryDetailCloseRef,
    unknownPersonCount, galleryFilterCount, includedKnownPersons, includedUnknownPersons, excludedPersonResults, excludedKnownPersonResults,
    excludedTagResults, excludedUnknownPersonResults, totalPages, currentPage, galleryExportStartCount,
    galleryExportFiltersDisabled, galleryExportDisabled, availablePersonsForPhoto, matchingPersonsForPhoto,
    selectedPhotoTags, availableTagsForPhoto, matchingTagsForPhoto, lightboxIndex, lightboxPhoto, isFirstOfPage,
    isLastOfPage, hasPrevPage, hasNextPage, canGoPrev, canGoNext, lightboxMeta,
    lightboxNavigating, lightboxLayoutRequest, completeLightboxLayout,
    galleryExportModalOpen, galleryExportScope, galleryExportPersonIds, galleryExportTagIds,
    galleryExportExcludePersonIds, galleryExportExcludeTagIds, galleryExportStartPhotoId,
    persons, tags,
    setPersonSearch, setTagSearch, setGalleryFiltersExpanded, setActiveGalleryFilterSection, setExcludePersonSearch,
    setExcludeTagSearch, setManualPersonId, setManualPersonSearch, setManualPersonNotice, setManualTagId,
    setManualTagSearch, setManualTagNotice, setManualTagName, setRichTextDraft, setLightboxRichTextDraft,
    setLightboxEditMode, setJumpPageInput, setSelectedFaceId, setActiveGalleryDetailTab, setGalleryDetailPinned,
    setSelectedGalleryPhotoIds, setLastSelectedGalleryPhotoId, setGalleryExportModalOpen, setGalleryExportScope,
    setGalleryExportPersonIds, setGalleryExportTagIds, setGalleryExportExcludePersonIds, setGalleryExportExcludeTagIds,
    setRecognitionNotice,
    closeGalleryDrawer, refreshGallery, handleTogglePersonFilter, handleToggleTagFilter, handleToggleUnknownPersonFilters,
    handleClearGalleryFilters, toggleGalleryFilterSection, handleToggleExcludePerson, handleToggleExcludeTag,
    openGalleryPhoto, openGalleryLightbox, closeGalleryLightbox, openLightboxPhotoDetail,
    copyCurrentGalleryFiltersToExport, openGalleryExportModal, openSelectedGalleryExportModal, openGalleryExportFromPhoto,
    handleExportGalleryPhotos, handleToggleGalleryExportPerson, handleToggleGalleryExportTag,
    handlePickGalleryImportFile, handleGalleryImportFileChange,
    renderFaceMatchSource, faceRejectionReasonLabel,
    handleAddPhotoPerson, handlePromotePhotoPerson, handleBindFace, handlePromoteFace, handleUnbindFace,
    handleUndoPromotePhotoPerson, handleDeletePhotoPerson, handleAddExistingPhotoTag, handleCreateAndAddPhotoTag,
    handleDeletePhotoTag, handleSaveRichText, handleSaveLightboxRichText,
    toggleGallerySelectionMode, handleGalleryCardClick, handleGalleryCheckboxClick, toggleCurrentGalleryPageSelection,
    handleDeleteSelectedGalleryPhotos, handleDeleteCurrentPhoto, handleReRecognize, handleJumpToPage,
    goPrevLightbox, goNextLightbox,
    recognitionNotice,
    photoIdSearchInput, setPhotoIdSearchInput, activePhotoIdSearch, photoIdSearchHint, handleClearPhotoIdSearch
  };
}

export type GalleryModel = ReturnType<typeof useGallery>;
