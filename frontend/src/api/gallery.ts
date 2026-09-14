import type {
  GalleryPhotoDetail,
  GallerySimilarityAutoDeletePreview,
  GallerySimilarityGroup,
  GallerySimilarityScan,
  GallerySimilarityScanOverview,
  PaginatedGallerySimilarityGroups,
  PaginatedGalleryPhotos,
  Task
} from "../types";
import { authFetch, jsonHeaders, parseBlobResponse, parseResponse, withWorkspaceContext } from "../lib/apiClient";

export type GalleryUploadMetadata = {
  person_ids: number[];
  tag_names: string[];
  rich_text?: string;
};
export type GalleryExportScope = "all" | "filtered" | "selected" | "from_start";
export type GalleryExportOptions = {
  scope: GalleryExportScope;
  photoIds?: number[];
  startPhotoId?: number;
  personIds?: number[];
  tagIds?: number[];
  excludePersonIds?: number[];
  excludeTagIds?: number[];
};

export async function listGalleryPhotos(
  personIds: number[],
  tagIds: number[],
  excludePersonIds: number[],
  excludeTagIds: number[],
  offset: number,
  limit: number
): Promise<PaginatedGalleryPhotos> {
  const url = new URL("/api/gallery/photos", window.location.origin);
  personIds.forEach((id) => url.searchParams.append("person_ids", String(id)));
  tagIds.forEach((id) => url.searchParams.append("tag_ids", String(id)));
  excludePersonIds.forEach((id) => url.searchParams.append("exclude_person_ids", String(id)));
  excludeTagIds.forEach((id) => url.searchParams.append("exclude_tag_ids", String(id)));
  url.searchParams.set("offset", String(offset));
  url.searchParams.set("limit", String(limit));
  return parseResponse<PaginatedGalleryPhotos>(await authFetch(url.pathname + url.search));
}

export async function getGalleryPhoto(photoId: number): Promise<GalleryPhotoDetail> {
  return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}`));
}

export async function deleteGalleryPhoto(photoId: number): Promise<void> {
  await parseResponse<{ status: string }>(
    await authFetch(`/api/gallery/photos/${photoId}`, { method: "DELETE" })
  );
}
export async function batchDeleteGalleryPhotos(photoIds: number[]): Promise<number> {
  const response = await parseResponse<{ deleted: number }>(
    await authFetch("/api/gallery/photos/batch-delete", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ photo_ids: photoIds })
    })
  );
  return response.deleted;
}
export async function addGalleryPhotoPerson(photoId: number, personId: number): Promise<GalleryPhotoDetail> {
  return parseResponse<GalleryPhotoDetail>(
    await authFetch(`/api/gallery/photos/${photoId}/persons`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ person_id: personId })
    })
  );
}

export async function createGallerySimilarityScan(payload: {
  person_id: number | null;
  include_cross_type: boolean;
  scan_type: "normal" | "mirror";
}): Promise<GallerySimilarityScan> {
  return parseResponse<GallerySimilarityScan>(
    await authFetch("/api/gallery/similarity-scans", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}
export async function previewNormalNearDuplicateAutoDelete(scanId: string): Promise<GallerySimilarityAutoDeletePreview> {
  return parseResponse<GallerySimilarityAutoDeletePreview>(
    await authFetch(`/api/gallery/similarity-scans/${scanId}/auto-delete-preview`)
  );
}
export async function autoDeleteExactMirrorGroups(scanId: string, deletePhotoIds?: number[]): Promise<{ deleted: number; scan: GallerySimilarityScan }> {
  return parseResponse<{ deleted: number; scan: GallerySimilarityScan }>(
    await authFetch(`/api/gallery/similarity-scans/${scanId}/auto-delete-exact-mirrors`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ delete_photo_ids: deletePhotoIds ?? [] })
    })
  );
}
export async function getLatestGallerySimilarityScan(personId: number | null, includeCrossType: boolean, scanType: "normal" | "mirror" = "normal"): Promise<GallerySimilarityScan | null> {
  const url = new URL("/api/gallery/similarity-scans/latest", window.location.origin);
  if (personId !== null) {
    url.searchParams.set("person_id", String(personId));
  }
  url.searchParams.set("include_cross_type", String(includeCrossType));
  url.searchParams.set("scan_type", scanType);
  return parseResponse<GallerySimilarityScan | null>(await authFetch(url.pathname + url.search));
}
export async function getGallerySimilarityScanOverview(): Promise<GallerySimilarityScanOverview> {
  return parseResponse<GallerySimilarityScanOverview>(
    await authFetch("/api/gallery/similarity-scans/overview")
  );
}

export async function listGallerySimilarityGroups(
  scanId: string,
  tier: "near_duplicate" | "same_scene",
  offset: number,
  limit: number
): Promise<PaginatedGallerySimilarityGroups> {
  const url = new URL(`/api/gallery/similarity-scans/${scanId}/groups`, window.location.origin);
  url.searchParams.set("tier", tier);
  url.searchParams.set("offset", String(offset));
  url.searchParams.set("limit", String(limit));
  return parseResponse<PaginatedGallerySimilarityGroups>(await authFetch(url.pathname + url.search));
}
export async function getGallerySimilarityGroup(scanId: string, groupId: number): Promise<GallerySimilarityGroup | null> { return parseResponse<GallerySimilarityGroup | null>(await authFetch(`/api/gallery/similarity-scans/${scanId}/groups/${groupId}`)); }
export async function updateGallerySimilarityGroup(scanId: string, groupId: number, reviewStatus: "pending" | "dismissed"): Promise<GallerySimilarityGroup> { return parseResponse<GallerySimilarityGroup>(await authFetch(`/api/gallery/similarity-scans/${scanId}/groups/${groupId}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ review_status: reviewStatus }) })); }
export async function promoteGalleryPhotoPersonSample(photoId: number, personId: number): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/persons/${personId}/sample`, { method: "POST" })); }
export async function bindGalleryFacePerson(photoId: number, faceId: number, personId: number): Promise<GalleryPhotoDetail> {
  return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/faces/${faceId}/person`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify({ person_id: personId })
  }));
}
export async function unbindGalleryFacePerson(photoId: number, faceId: number): Promise<GalleryPhotoDetail> {
  return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/faces/${faceId}/person`, { method: "DELETE" }));
}
export async function promoteGalleryFaceSample(photoId: number, faceId: number): Promise<GalleryPhotoDetail> {
  return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/faces/${faceId}/sample`, {
    method: "POST"
  }));
}
export async function undoGalleryPhotoPersonSample(photoId: number, personId: number): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/persons/${personId}/sample`, { method: "DELETE" })); }
export async function deleteGalleryPhotoPerson(photoId: number, personId: number): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/persons/${personId}`, { method: "DELETE" })); }
export async function addGalleryPhotoTag(photoId: number, payload: { tagId?: number; name?: string }): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/tags`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload.tagId ? { tag_id: payload.tagId } : { name: payload.name }) })); }
export async function deleteGalleryPhotoTag(photoId: number, tagId: number): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/tags/${tagId}`, { method: "DELETE" })); }
export async function importGalleryPhotos(files: File[], metadata: GalleryUploadMetadata[]): Promise<Task> { const form = new FormData(); files.forEach((file) => form.append("files", file)); form.append("metadata_json", JSON.stringify(metadata)); return parseResponse<Task>(await authFetch("/api/gallery/photos/import", { method: "POST", body: form })); }
export async function importGalleryRichPhotos(files: File[], metadata: GalleryUploadMetadata[]): Promise<Task> { const form = new FormData(); files.forEach((file) => form.append("files", file)); form.append("metadata_json", JSON.stringify(metadata)); return parseResponse<Task>(await authFetch("/api/gallery/rich-photos/import", { method: "POST", body: form })); }
export function getGalleryExportUrl(options: GalleryExportOptions): string { const url = new URL("/api/gallery/photos/export", window.location.origin); url.searchParams.set("scope", options.scope); options.personIds?.forEach((id) => url.searchParams.append("person_ids", String(id))); options.tagIds?.forEach((id) => url.searchParams.append("tag_ids", String(id))); options.excludePersonIds?.forEach((id) => url.searchParams.append("exclude_person_ids", String(id))); options.excludeTagIds?.forEach((id) => url.searchParams.append("exclude_tag_ids", String(id))); return withWorkspaceContext(url.pathname + url.search); }
export async function downloadGalleryExport(options: GalleryExportOptions): Promise<{ blob: Blob; filename: string }> {
  const response = await authFetch("/api/gallery/photos/export", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      scope: options.scope,
      photo_ids: options.photoIds ?? [],
      start_photo_id: options.startPhotoId ?? null,
      person_ids: options.personIds ?? [],
      tag_ids: options.tagIds ?? [],
      exclude_person_ids: options.excludePersonIds ?? [],
      exclude_tag_ids: options.excludeTagIds ?? []
    })
  });
  return parseBlobResponse(response, "gallery_export.zip", "导出失败。");
}
export async function importGalleryExportZip(file: File): Promise<Task> { const formData = new FormData(); formData.append("file", file); return parseResponse<Task>(await authFetch("/api/gallery/photos/import-zip", { method: "POST", body: formData })); }
export async function updateGalleryPhotoRichText(photoId: number, richText: string): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/rich-text`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ rich_text: richText }) })); }
export async function getTask(taskId: string): Promise<Task> { return parseResponse<Task>(await authFetch(`/api/tasks/${taskId}`)); }
export async function reRecognizeGalleryPhoto(photoId: number): Promise<GalleryPhotoDetail> { return parseResponse<GalleryPhotoDetail>(await authFetch(`/api/gallery/photos/${photoId}/re-recognize`, { method: "POST" })); }
export async function reRecognizeUnknownGalleryPhotos(): Promise<{ total: number; succeeded: number; failed: number }> { return parseResponse<{ total: number; succeeded: number; failed: number }>(await authFetch("/api/gallery/photos/re-recognize-unknown", { method: "POST" })); }
export async function clearUnknownGalleryPersonTags(): Promise<{ total: number; cleared: number; kept: number }> { return parseResponse<{ total: number; cleared: number; kept: number }>(await authFetch("/api/gallery/photos/clear-unknown-tags", { method: "POST" })); }
