import { useEffect, useMemo, useRef, useState } from "react";

import {
  addPersonSamples,
  batchDeletePersons,
  bindPersonTag,
  clearUnknownGalleryPersonTags,
  createPerson,
  deletePerson,
  deletePersonSample,
  downloadPersonExport,
  getTask,
  importPersonSamples,
  listPersonSamples,
  listPersonTags,
  renamePerson,
  reRecognizeUnknownGalleryPhotos,
  unbindPersonTag
} from "../api";
import type { ConfirmDialogOptions } from "../components/ConfirmDialog";
import { formatError } from "../lib/formatError";
import { isSystemUnknownPerson } from "../lib/personPicker";
import type { PageKey } from "../lib/routing";
import { sortByPinyinName } from "../lib/sort";
import { isTerminalTask } from "../lib/taskStatus";
import type { Person, SamplePhoto, Tag, Task } from "../types";
import { usePolling } from "./usePolling";
import type { PendingSampleUpload } from "./useUpload";
import { filterPersonMatches } from "../lib/personPicker";

type UsePeopleOptions = {
  persons: Person[];
  tags: Tag[];
  confirm: (options: ConfirmDialogOptions) => Promise<boolean>;
  refreshPeople: () => Promise<Person[]>;
  refreshTags: () => Promise<unknown>;
  refreshGallery: () => Promise<void>;
  onNavigate: (page: PageKey) => void;
  onOpenGalleryPhoto: (photoId: number) => Promise<void>;
  canAddSamples: boolean;
  canDeleteSamples: boolean;
  canEditSamples: boolean;
  canEditGallery: boolean;
};

export function usePeople({
  persons,
  tags,
  confirm,
  refreshPeople,
  refreshTags,
  refreshGallery,
  onNavigate,
  onOpenGalleryPhoto,
  canAddSamples,
  canDeleteSamples,
  canEditSamples,
  canEditGallery
}: UsePeopleOptions) {
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
  const [recognitionNotice, setRecognitionNotice] = useState<{ id: number; message: string } | null>(null);

  const filteredPeopleInLibrary = useMemo(
    () => filterPersonMatches(persons, peopleSearch),
    [peopleSearch, persons]
  );
  const unknownPersonCount = useMemo(() => persons.filter((person) => person.is_unknown).length, [persons]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [importTask, setImportTask] = useState<Task | null>(null);
  const [pendingSampleUploads, setPendingSampleUploads] = useState<PendingSampleUpload[]>([]);
  const [highlightedSampleId, setHighlightedSampleId] = useState<number | null>(null);
  const importFileRef = useRef<HTMLInputElement | null>(null);
  const peopleMainRef = useRef<HTMLElement | null>(null);
  const selectedPersonIsSystemUnknown = isSystemUnknownPerson(selectedPerson);
  const selectedPersonDeleteCount = useMemo(
    () => selectedPersonDeleteIds.filter((id) => !isSystemUnknownPerson(persons.find((person) => person.id === id))).length,
    [persons, selectedPersonDeleteIds]
  );
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
    if (highlightedSampleId === null || !samples.some((sample) => sample.id === highlightedSampleId)) {
      return undefined;
    }
    document.getElementById(`sample-${highlightedSampleId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
    const timer = window.setTimeout(() => setHighlightedSampleId(null), 2600);
    return () => window.clearTimeout(timer);
  }, [highlightedSampleId, samples]);
  usePolling(
    async () => {
      if (!importTask || isTerminalTask(importTask)) {
        return;
      }
      try {
        const nextTask = await getTask(importTask.id);
        setImportTask(nextTask);
        if (nextTask.status === "completed") {
          await refreshPeople();
          setBusy(false);
        }
        if (nextTask.status === "failed" || nextTask.status === "canceled") {
          setBusy(false);
        }
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "导入轮询失败。");
        setBusy(false);
      }
    },
    1500,
    Boolean(importTask && !isTerminalTask(importTask))
  );
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
      onNavigate("people");
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
      await Promise.all([refreshPeople(), refreshGallery()]);
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
      await Promise.all([refreshPeople(), refreshGallery()]);
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
      await Promise.all([refreshPeople(), refreshGallery()]);
      window.alert(`已完成重新识别：共 ${result.total} 张，成功 ${result.succeeded} 张，失败 ${result.failed} 张。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量重新识别未知人物失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleClearUnknownPersonTags() {
    if (
      !await confirm({
        title: "清空未知人物标签",
        message: "确认清空图库所有图片上的未知人物标签吗？仅当图片至少已绑定一个已知人物标签时才会移除其未知人物标签，否则该标签会保留。",
        confirmLabel: "开始清空",
        tone: "danger",
      })
    ) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await clearUnknownGalleryPersonTags();
      await Promise.all([refreshPeople(), refreshGallery()]);
      window.alert(`已完成清空：共 ${result.total} 张图片带未知人物标签，已清除 ${result.cleared} 张，保留 ${result.kept} 张。`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "批量清空未知人物标签失败。");
    } finally {
      setBusy(false);
    }
  }

  async function handleExportPersons() {
    setBusy(true);
    setError(null);
    try {
      const { blob, filename } = await downloadPersonExport();
      const downloadUrl = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = downloadUrl;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(downloadUrl);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导出样本库失败。");
    } finally {
      setBusy(false);
    }
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
      if (isTerminalTask(task)) {
        if (task.status === "completed") {
          await refreshPeople();
        }
        setBusy(false);
      }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "导入失败。");
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

  function handleOpenMatchedSample(personId: number, samplePhotoId: number) {
    const person = persons.find((item) => item.id === personId);
    if (!person) {
      setError("对应人物已删除，无法打开命中样本。");
      return;
    }
    pendingSampleUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
    setPendingSampleUploads([]);
    setSelectedPerson(person);
    setHighlightedSampleId(samplePhotoId);
    onNavigate("people");
    window.requestAnimationFrame(() => {
      peopleMainRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
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
      await Promise.all([refreshTags(), refreshGallery()]);
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
  async function handleOpenSampleSource(photoId: number) {
    onNavigate("gallery");
    await onOpenGalleryPhoto(photoId);
  }

  useEffect(() => {
    setSelectedPerson((current) => {
      if (!persons.length) {
        return null;
      }
      if (!current) {
        return persons[0] ?? null;
      }
      return persons.find((person) => person.id === current.id) ?? persons[0] ?? null;
    });
    setSelectedPersonDeleteIds((current) => current.filter((id) => persons.some((person) => person.id === id)));
  }, [persons]);

  return {
    error, setError, busy, canAddSamples, canDeleteSamples, canEditSamples, canEditGallery,
    persons, tags, selectedPerson, peopleSearch, peopleBatchDeleteMode, selectedPersonDeleteIds, samples, personTags,
    personTagSelectId, personTagName, newPersonName, renameValue, importFileRef, importTask,
    pendingSampleUploads, highlightedSampleId, peopleMainRef,
    filteredPeopleInLibrary, unknownPersonCount, selectedPersonIsSystemUnknown, selectedPersonDeleteCount,
    setPeopleSearch, setNewPersonName, setRenameValue, setPersonTagSelectId, setPersonTagName,
    setSelectedPersonDeleteIds, setSelectedPerson,
    handleCreatePerson, handleRenamePerson, handlePickSampleFiles, handleConfirmSampleUpload, handleRemovePendingSample,
    handleDeleteSample, togglePeopleBatchDeleteMode, handleDeleteSelectedPersons, handleDeleteCurrentPerson,
    handleReRecognizeAllUnknownPhotos, handleClearUnknownPersonTags, handleExportPersons, handlePickImportFile,
    handleImportFileChange, handleSelectPerson, handleOpenMatchedSample, handleOpenSampleSource, handleBindPersonTag, handleUnbindPersonTag
  };
}

export type PeopleModel = ReturnType<typeof usePeople>;
