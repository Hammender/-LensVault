import { useState } from "react";

import { getTask, importGalleryPhotos, importGalleryRichPhotos, type GalleryUploadMetadata } from "../api";
import { formatError } from "../lib/formatError";
import { mergePersonIds } from "../lib/personPicker";
import { isTerminalTask } from "../lib/taskStatus";
import type { Person, Tag, Task } from "../types";
import { splitCommaList } from "../lib/utils";
import { usePolling } from "./usePolling";

export type PendingSampleUpload = {
  file: File;
  previewUrl: string;
};

export type PendingGalleryUpload = {
  file: File;
  previewUrl: string;
  personIds: number[];
  personSearch: string;
  personNotice: string | null;
  tagNamesText: string;
  richText: string;
};

export type UploadMode = "normal" | "rich";

type UseUploadOptions = {
  persons: Person[];
  tags: Tag[];
  refreshPeople: () => Promise<unknown>;
  refreshTags: () => Promise<unknown>;
  refreshGallery: () => Promise<unknown>;
  canAddGallery: boolean;
  canAddVideos: boolean;
};

export function useUpload({
  persons,
  tags,
  refreshPeople,
  refreshTags,
  refreshGallery,
  canAddGallery,
  canAddVideos
}: UseUploadOptions) {
  const [error, setError] = useState<string | null>(null);
  const [pendingGalleryUploads, setPendingGalleryUploads] = useState<PendingGalleryUpload[]>([]);
  const [batchApplyPersonIds, setBatchApplyPersonIds] = useState<number[]>([]);
  const [batchApplyPersonSearch, setBatchApplyPersonSearch] = useState("");
  const [batchApplyPersonNotice, setBatchApplyPersonNotice] = useState<string | null>(null);
  const [batchApplyTagNames, setBatchApplyTagNames] = useState("");
  const [uploadMode, setUploadMode] = useState<UploadMode>("normal");
  const [galleryUploadBusy, setGalleryUploadBusy] = useState(false);
  const [task, setTask] = useState<Task | null>(null);
  const richTag = tags.find((tag) => tag.name === "图文") ?? null;

  usePolling(
    async () => {
      if (!task || isTerminalTask(task)) {
        return;
      }
      try {
        const nextTask = await getTask(task.id);
        setTask(nextTask);
        if (nextTask.status === "completed") {
          await Promise.all([refreshPeople(), refreshTags(), refreshGallery()]);
        }
      } catch (cause) {
        setError(formatError(cause, "任务轮询失败。"));
      }
    },
    1500,
    Boolean(task && !isTerminalTask(task))
  );

  function handlePickGalleryFiles(files: FileList | null) {
    if (!files?.length) {
      return;
    }
    setPendingGalleryUploads((current) => [
      ...current,
      ...Array.from(files).map((file) => ({
        file,
        previewUrl: URL.createObjectURL(file),
        personIds: [],
        personSearch: "",
        personNotice: null,
        tagNamesText: "",
        richText: ""
      }))
    ]);
  }

  function handleUpdatePendingGallery(index: number, changes: Partial<PendingGalleryUpload>) {
    setPendingGalleryUploads((current) =>
      current.map((item, i) => (i === index ? { ...item, ...changes } : item))
    );
  }

  function handleApplyBatchMetadataToAll() {
    if (batchApplyPersonSearch.trim()) {
      setBatchApplyPersonNotice("请先从候选列表确认人物，或清空人物搜索内容。");
      return;
    }
    const tagNames = splitCommaList(batchApplyTagNames);
    if (batchApplyPersonIds.length === 0 && tagNames.length === 0) {
      return;
    }
    setPendingGalleryUploads((current) =>
      current.map((item) => {
        const mergedTags = Array.from(new Set([...splitCommaList(item.tagNamesText), ...tagNames]));
        return {
          ...item,
          personIds: mergePersonIds(item.personIds, batchApplyPersonIds),
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
    const hasUnconfirmedPerson =
      Boolean(batchApplyPersonSearch.trim()) || pendingGalleryUploads.some((item) => item.personSearch.trim());
    const selectablePersonIds = new Set(persons.filter((person) => !person.is_unknown).map((person) => person.id));
    const hasInvalidPerson = pendingGalleryUploads.some((item) =>
      item.personIds.some((personId) => !selectablePersonIds.has(personId))
    );
    if (hasUnconfirmedPerson || hasInvalidPerson) {
      const message = "所选人物不存在，请先在样本库创建人物后再上传。";
      if (batchApplyPersonSearch.trim()) setBatchApplyPersonNotice(message);
      setPendingGalleryUploads((current) =>
        current.map((item) => ({
          ...item,
          personNotice:
            item.personSearch.trim() || item.personIds.some((personId) => !selectablePersonIds.has(personId))
              ? message
              : item.personNotice
        }))
      );
      setError(message);
      return;
    }
    setGalleryUploadBusy(true);
    setError(null);
    try {
      const files = pendingGalleryUploads.map((item) => item.file);
      const metadata: GalleryUploadMetadata[] = pendingGalleryUploads.map((item) => ({
        person_ids: item.personIds,
        tag_names: splitCommaList(item.tagNamesText),
        rich_text: uploadMode === "rich" ? item.richText.trim() : undefined
      }));
      const nextTask =
        uploadMode === "rich"
          ? await importGalleryRichPhotos(files, metadata)
          : await importGalleryPhotos(files, metadata);
      setTask(nextTask);
      pendingGalleryUploads.forEach((item) => URL.revokeObjectURL(item.previewUrl));
      setPendingGalleryUploads([]);
      setBatchApplyPersonIds([]);
      setBatchApplyPersonSearch("");
      setBatchApplyPersonNotice(null);
      setBatchApplyTagNames("");
    } catch (cause) {
      setError(formatError(cause, "展示图上传失败。"));
    } finally {
      setGalleryUploadBusy(false);
    }
  }

  return {
    error,
    setError,
    canAddGallery,
    canAddVideos,
    persons,
    pendingGalleryUploads,
    batchApplyPersonIds,
    batchApplyPersonSearch,
    batchApplyPersonNotice,
    batchApplyTagNames,
    uploadMode,
    galleryUploadBusy,
    task,
    richTag,
    setUploadMode,
    setBatchApplyPersonIds,
    setBatchApplyPersonSearch,
    setBatchApplyPersonNotice,
    setBatchApplyTagNames,
    handlePickGalleryFiles,
    handleUpdatePendingGallery,
    handleApplyBatchMetadataToAll,
    handleRemovePendingGallery,
    handleConfirmGalleryUpload
  };
}

export type UploadModel = ReturnType<typeof useUpload>;
