import { useState } from "react";

import type { Task } from "../types";

export type PendingSampleUpload = {
  file: File;
  previewUrl: string;
};

export type PendingGalleryUpload = {
  file: File;
  previewUrl: string;
  personNamesText: string;
  tagNamesText: string;
  richText: string;
};

export type UploadMode = "normal" | "rich";

export function useUploadController() {
  const [pendingSampleUploads, setPendingSampleUploads] = useState<PendingSampleUpload[]>([]);
  const [pendingGalleryUploads, setPendingGalleryUploads] = useState<PendingGalleryUpload[]>([]);
  const [batchApplyPersonNames, setBatchApplyPersonNames] = useState("");
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
    batchApplyPersonNames,
    setBatchApplyPersonNames,
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
