import { useEffect, useMemo, useState } from "react";

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
  listGalleryPhotos,
  listPersonSamples,
  listPersons,
  listPersonTags,
  listTags,
  renamePerson,
  unbindPersonTag,
  type GalleryUploadMetadata
} from "./api";
import type { GalleryPhotoDetail, GalleryPhotoListItem, Person, SamplePhoto, Tag, Task } from "./types";

type PageKey = "gallery" | "people" | "upload";

type PendingSampleUpload = {
  file: File;
  previewUrl: string;
};

type PendingGalleryUpload = {
  file: File;
  previewUrl: string;
  personNamesText: string;
  tagNamesText: string;
};

const galleryPageSize = 18;

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
  if (hash === "people" || hash === "upload") {
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
        .split(",")
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
  const [selectedPhoto, setSelectedPhoto] = useState<GalleryPhotoDetail | null>(null);
  const [manualPersonId, setManualPersonId] = useState("");
  const [manualTagId, setManualTagId] = useState("");
  const [manualTagName, setManualTagName] = useState("");
  const [selectedPerson, setSelectedPerson] = useState<Person | null>(null);
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
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const filteredPersons = useMemo(() => {
    const keyword = personSearch.trim().toLowerCase();
    if (!keyword) {
      return persons;
    }
    return persons.filter((person) => person.display_name.toLowerCase().includes(keyword));
  }, [personSearch, persons]);

  const filteredTags = useMemo(() => {
    const keyword = tagSearch.trim().toLowerCase();
    if (!keyword) {
      return tags;
    }
    return tags.filter((tag) => tag.name.toLowerCase().includes(keyword));
  }, [tagSearch, tags]);

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
    setTags(await listTags());
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
    setPersonTags(await listPersonTags(personId));
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
      setSelectedPhoto(await getGalleryPhoto(photoId));
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
      setPersonTags(next);
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
      setPersonTags(next);
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
        tagNamesText: ""
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
        tag_names: splitCommaList(item.tagNamesText)
      }));
      const nextTask = await importGalleryPhotos(files, metadata);
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

  const availablePersonsForPhoto = selectedPhoto
    ? persons.filter((person) => !selectedPhoto.persons.some((tag) => tag.person_id === person.id))
    : persons;

  const availableTagsForPhoto = selectedPhoto
    ? tags.filter((tag) => !selectedPhoto.tags.some((item) => item.id === tag.id))
    : tags;

  const lightboxIndex = lightboxPhotoId === null ? -1 : galleryPhotos.findIndex((photo) => photo.id === lightboxPhotoId);
  const lightboxPhoto = lightboxIndex >= 0 ? galleryPhotos[lightboxIndex] : null;
  const canGoPrev = lightboxIndex > 0;
  const canGoNext = lightboxIndex >= 0 && lightboxIndex < galleryPhotos.length - 1;

  function goPrevLightbox() {
    if (!canGoPrev || lightboxIndex < 0) {
      return;
    }
    setLightboxPhotoId(galleryPhotos[lightboxIndex - 1].id);
  }

  function goNextLightbox() {
    if (!canGoNext || lightboxIndex < 0) {
      return;
    }
    setLightboxPhotoId(galleryPhotos[lightboxIndex + 1].id);
  }

  useEffect(() => {
    if (!lightboxPhoto) {
      return undefined;
    }
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        closeGalleryLightbox();
      } else if (event.key === "ArrowLeft") {
        goPrevLightbox();
      } else if (event.key === "ArrowRight") {
        goNextLightbox();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [lightboxPhoto, lightboxIndex, canGoPrev, canGoNext]);

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
            ["upload", "页面 C · 展示图上传"]
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
              <input value={personSearch} onChange={(event) => setPersonSearch(event.target.value)} placeholder="搜索人物名" />
              <div className="chip-cloud">
                {filteredPersons.map((person) => {
                  const active = selectedPersonIds.includes(person.id);
                  return (
                    <button
                      key={person.id}
                      className={active ? "soft-chip active" : "soft-chip"}
                      onClick={() => {
                        const next = active
                          ? selectedPersonIds.filter((id) => id !== person.id)
                          : [...selectedPersonIds, person.id];
                        setSelectedPersonIds(next);
                        void refreshGallery(0, next, selectedTagIds);
                      }}
                    >
                      {person.display_name}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="filter-group">
              <label>按普通标签筛选</label>
              <input value={tagSearch} onChange={(event) => setTagSearch(event.target.value)} placeholder="搜索标签" />
              <div className="chip-cloud">
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
              {galleryPhotos.map((photo) => (
                <article key={photo.id} className="photo-card-wrap">
                  <button className="photo-card" onClick={() => openGalleryLightbox(photo.id)}>
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
                        {photo.tags.map((tag) => (
                          <small key={`${photo.id}-t-${tag.id}`} className="pill muted">
                            #{tag.name}
                          </small>
                        ))}
                      </div>
                    </div>
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
              ))}
              {galleryPhotos.length === 0 && <div className="empty-card">当前筛选条件下没有展示图。</div>}
            </div>

            <div className="pagination-row">
              <button disabled={galleryOffset === 0} onClick={() => void refreshGallery(Math.max(0, galleryOffset - galleryPageSize))}>
                上一页
              </button>
              <span>
                {galleryTotal === 0 ? 0 : galleryOffset + 1} - {Math.min(galleryOffset + galleryPageSize, galleryTotal)} / {galleryTotal}
              </span>
              <button
                disabled={galleryOffset + galleryPageSize >= galleryTotal}
                onClick={() => void refreshGallery(galleryOffset + galleryPageSize)}
              >
                下一页
              </button>
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
                    {selectedPhoto.tags.map((tag) => (
                      <button key={tag.id} className="pill muted action-pill" onClick={() => void handleDeletePhotoTag(tag.id)}>
                        #{tag.name}
                      </button>
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
              </div>
            </div>

            <div className="inline-editor">
              <input value={newPersonName} onChange={(event) => setNewPersonName(event.target.value)} placeholder="输入新人物名称" />
              <button disabled={busy || !newPersonName.trim()} onClick={() => void handleCreatePerson()}>
                创建人物
              </button>
            </div>

            <div className="person-list">
              {persons.map((person) => (
                <article key={person.id} className="person-card-wrap">
                  <button
                    className={selectedPerson?.id === person.id ? "person-card active" : "person-card"}
                    onClick={() => setSelectedPerson(person)}
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
            </div>
          </section>

          <section className="panel people-main">
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
                        {tags
                          .filter((tag) => !personTags.some((item) => item.id === tag.id))
                          .map((tag) => (
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
                  {samples.map((sample) => (
                    <article key={sample.id} className="sample-card">
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
                  ))}
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

            <label className="upload-box large">
              <input type="file" multiple accept="image/*" onChange={(event) => handlePickGalleryFiles(event.target.files)} />
              <strong>拖入或选择展示图片</strong>
              <span>先预览并填写每张图的人物和标签，确认后再统一上传到后端识别。</span>
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
          <div className="lightbox-shell" onClick={(event) => event.stopPropagation()}>
            <button className="lightbox-close" onClick={() => closeGalleryLightbox()}>
              关闭
            </button>
            <button className="lightbox-arrow left" disabled={!canGoPrev} onClick={() => goPrevLightbox()}>
              ‹
            </button>
            <img className="lightbox-image" src={lightboxPhoto.original_url} alt="大图预览" />
            <button className="lightbox-arrow right" disabled={!canGoNext} onClick={() => goNextLightbox()}>
              ›
            </button>
          </div>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}
    </div>
  );
}
