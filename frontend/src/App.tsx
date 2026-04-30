import { useEffect, useMemo, useRef, useState } from "react";

import Statistics from "./Statistics";
import { sortByPinyinName } from "./sort";
import {
  addGalleryPhotoPerson,
  addGalleryPhotoTag,
  addPersonSamples,
  batchDeleteGalleryPhotos,
  batchDeletePersons,
  bindPersonTag,
  createPerson,
  deleteGalleryPhoto,
  deleteGalleryPhotoPerson,
  deleteGalleryPhotoTag,
  deletePerson,
  deletePersonSample,
  getGalleryPhoto,
  getTask,
  importGalleryPhotos,
  importGalleryRichPhotos,
  listGalleryPhotos,
  listPersonSamples,
  listPersons,
  listPersonTags,
  listTags,
  renamePerson,
  reRecognizeGalleryPhoto,
  reRecognizeUnknownGalleryPhotos,
  updateGalleryPhotoRichText,
  unbindPersonTag,
  type GalleryUploadMetadata
} from "./api";
import type { GalleryPhotoDetail, GalleryPhotoListItem, Person, SamplePhoto, Tag, Task } from "./types";

type PageKey = "gallery" | "people" | "upload" | "statistics";

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

function routeFromHash(): PageKey {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (hash === "people" || hash === "upload" || hash === "statistics") {
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

export default function App() {
  const [page, setPageState] = useState<PageKey>(() => routeFromHash());
  const [persons, setPersons] = useState<Person[]>([]);
  const [tags, setTags] = useState<Tag[]>([]);
  const [galleryPhotos, setGalleryPhotos] = useState<GalleryPhotoListItem[]>([]);
  const [galleryTotal, setGalleryTotal] = useState(0);
  const [galleryOffset, setGalleryOffset] = useState(0);
  const [galleryBatchDeleteMode, setGalleryBatchDeleteMode] = useState(false);
  const [selectedGalleryDeleteIds, setSelectedGalleryDeleteIds] = useState<number[]>([]);
  const [lightboxPhotoId, setLightboxPhotoId] = useState<number | null>(null);
  const [selectedPersonIds, setSelectedPersonIds] = useState<number[]>([]);
  const [selectedTagIds, setSelectedTagIds] = useState<number[]>([]);
  const [personSearch, setPersonSearch] = useState("");
  const [tagSearch, setTagSearch] = useState("");
  const [showUnknownPersons, setShowUnknownPersons] = useState(false);
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jumpPageInput, setJumpPageInput] = useState("");
  const peopleMainRef = useRef<HTMLElement | null>(null);

  const richTag = useMemo(() => tags.find((tag) => tag.name === "图文") ?? null, [tags]);

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

  async function refreshGallery(nextOffset = galleryOffset, personIds = selectedPersonIds, tagIds = selectedTagIds) {
    const response = await listGalleryPhotos(personIds, tagIds, nextOffset, galleryPageSize);
    setGalleryPhotos(response.items);
    setGalleryTotal(response.total);
    setGalleryOffset(response.offset);
    setSelectedGalleryDeleteIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
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
    void refreshGallery(0, next, selectedTagIds);
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
    void refreshGallery(0, next, selectedTagIds);
  }

  useEffect(() => {
    const onHashChange = () => setPageState(routeFromHash());
    window.addEventListener("hashchange", onHashChange);
    if (!window.location.hash) {
      setRoute("gallery");
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

  function toggleGalleryBatchDeleteMode() {
    setGalleryBatchDeleteMode((current) => {
      if (current) {
        setSelectedGalleryDeleteIds([]);
      }
      return !current;
    });
  }

  async function handleDeleteSelectedGalleryPhotos() {
    if (selectedGalleryDeleteIds.length === 0) {
      return;
    }
    if (!window.confirm(`确认删除选中的 ${selectedGalleryDeleteIds.length} 张图库图片吗？这会删除图片文件、识别记录和向量数据。`)) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await batchDeleteGalleryPhotos(selectedGalleryDeleteIds);
      if (selectedPhoto && selectedGalleryDeleteIds.includes(selectedPhoto.id)) {
        setSelectedPhoto(null);
      }
      setSelectedGalleryDeleteIds([]);
      setGalleryBatchDeleteMode(false);
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
      setSelectedGalleryDeleteIds((current) => current.filter((id) => id !== selectedPhoto.id));
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
        const response = await listGalleryPhotos(selectedPersonIds, selectedTagIds, newOffset, galleryPageSize);
        setGalleryPhotos(response.items);
        setGalleryTotal(response.total);
        setGalleryOffset(response.offset);
        setSelectedGalleryDeleteIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
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
        const response = await listGalleryPhotos(selectedPersonIds, selectedTagIds, newOffset, galleryPageSize);
        setGalleryPhotos(response.items);
        setGalleryTotal(response.total);
        setGalleryOffset(response.offset);
        setSelectedGalleryDeleteIds((current) => current.filter((id) => response.items.some((photo) => photo.id === id)));
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
            ["statistics", "页面 D · 数据统计"]
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
                  return (
                    <button
                      key={tag.id}
                      className={active ? "soft-chip active" : "soft-chip"}
                      onClick={() => {
                        const next = active ? selectedTagIds.filter((id) => id !== tag.id) : [...selectedTagIds, tag.id];
                        setSelectedTagIds(next);
                        void refreshGallery(0, selectedPersonIds, next);
                      }}
                    >
                      #{tag.name}
                    </button>
                  );
                })}
                {filteredTags.length === 0 && <span className="filter-empty">没有匹配的普通标签</span>}
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
                <button disabled={busy} onClick={() => toggleGalleryBatchDeleteMode()}>
                  {galleryBatchDeleteMode ? "取消批量" : "批量删除"}
                </button>
                <button
                  disabled={busy || !galleryBatchDeleteMode || selectedGalleryDeleteIds.length === 0}
                  onClick={() => void handleDeleteSelectedGalleryPhotos()}
                >
                  删除选中（{selectedGalleryDeleteIds.length}）
                </button>
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
                  {galleryBatchDeleteMode && (
                    <label className="corner-check">
                      <input
                        type="checkbox"
                        checked={selectedGalleryDeleteIds.includes(photo.id)}
                        onChange={(event) => {
                          setSelectedGalleryDeleteIds((current) =>
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
