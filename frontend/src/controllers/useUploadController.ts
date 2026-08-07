import { useState } from "react";

import type { Task } from "../types";

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

export function useUploadController() {
  const [pendingSampleUploads, setPendingSampleUploads] = useState<PendingSampleUpload[]>([]);
  const [pendingGalleryUploads, setPendingGalleryUploads] = useState<PendingGalleryUpload[]>([]);
  const [batchApplyPersonIds, setBatchApplyPersonIds] = useState<number[]>([]);
  const [batchApplyPersonSearch, setBatchApplyPersonSearch] = useState("");
  const [batchApplyPersonNotice, setBatchApplyPersonNotice] = useState<string | null>(null);
  const [batchApplyTagNames, setBatchApplyTagNames] = useState("");
  const [uploadMode, setUploadMode] = useState<UploadMode>("normal");
  const [galleryUploadBusy, setGalleryUploadBusy] = useState(false);
  const [importTask, setImportTask] = useState<Task | null>(null);
  const [galleryImportTask, setGalleryImportTask] = useState<Task | null>(null);

  return {
    pendingSampleUploads,
    setPendingSampleUploads,
    pendingGalleryUploads,
    setPendingGalleryUploads,
    batchApplyPersonIds,
    setBatchApplyPersonIds,
    batchApplyPersonSearch,
    setBatchApplyPersonSearch,
    batchApplyPersonNotice,
    setBatchApplyPersonNotice,
    batchApplyTagNames,
    setBatchApplyTagNames,
    uploadMode,
    setUploadMode,
    galleryUploadBusy,
    setGalleryUploadBusy,
    importTask,
    setImportTask,
    galleryImportTask,
    setGalleryImportTask
  };
}
