import type {
  GalleryPhotoDetail,
  PaginatedGalleryPhotos,
  Person,
  SamplePhoto,
  Tag,
  Task,
  TagStatistics,
  PersonStatistics,
  UploadHistory,
  UploadSummary
} from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function listPersons(isUnknown?: boolean): Promise<Person[]> {
  const url = new URL("/api/persons", window.location.origin);
  if (typeof isUnknown === "boolean") {
    url.searchParams.set("is_unknown", String(isUnknown));
  }
  return parse<Person[]>(await fetch(url.pathname + url.search));
}

export async function createPerson(name: string, note?: string): Promise<Person> {
  return parse<Person>(
    await fetch("/api/persons", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name, note: note || null })
    })
  );
}

export async function renamePerson(personId: number, name: string): Promise<Person> {
  return parse<Person>(
    await fetch(`/api/persons/${personId}/rename`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function deletePerson(personId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/persons/${personId}`, {
      method: "DELETE"
    })
  );
}

export async function batchDeletePersons(personIds: number[]): Promise<number> {
  const response = await parse<{ deleted: number }>(
    await fetch("/api/persons/batch-delete", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ person_ids: personIds })
    })
  );
  return response.deleted;
}

export async function listPersonSamples(personId: number): Promise<SamplePhoto[]> {
  return parse<SamplePhoto[]>(await fetch(`/api/persons/${personId}/samples`));
}

export async function addPersonSamples(personId: number, files: File[]): Promise<SamplePhoto[]> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return parse<SamplePhoto[]>(
    await fetch(`/api/persons/${personId}/samples`, {
      method: "POST",
      body: form
    })
  );
}

export async function listPersonTags(personId: number): Promise<Tag[]> {
  return parse<Tag[]>(await fetch(`/api/persons/${personId}/tags`));
}

export async function bindPersonTag(personId: number, payload: { tagId?: number; name?: string }): Promise<Tag[]> {
  return parse<Tag[]>(
    await fetch(`/api/persons/${personId}/tags`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload.tagId ? { tag_id: payload.tagId } : { name: payload.name })
    })
  );
}

export async function unbindPersonTag(personId: number, tagId: number): Promise<Tag[]> {
  return parse<Tag[]>(
    await fetch(`/api/persons/${personId}/tags/${tagId}`, {
      method: "DELETE"
    })
  );
}

export async function deletePersonSample(personId: number, samplePhotoId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/persons/${personId}/samples/${samplePhotoId}`, {
      method: "DELETE"
    })
  );
}

export async function listTags(): Promise<Tag[]> {
  return parse<Tag[]>(await fetch("/api/tags"));
}

export async function createTag(name: string): Promise<Tag> {
  return parse<Tag>(
    await fetch("/api/tags", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

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
  return parse<PaginatedGalleryPhotos>(await fetch(url.pathname + url.search));
}

export async function getGalleryPhoto(photoId: number): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(await fetch(`/api/gallery/photos/${photoId}`));
}

export async function deleteGalleryPhoto(photoId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/gallery/photos/${photoId}`, {
      method: "DELETE"
    })
  );
}

export async function batchDeleteGalleryPhotos(photoIds: number[]): Promise<number> {
  const response = await parse<{ deleted: number }>(
    await fetch("/api/gallery/photos/batch-delete", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ photo_ids: photoIds })
    })
  );
  return response.deleted;
}

export async function addGalleryPhotoPerson(photoId: number, personId: number): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(
    await fetch(`/api/gallery/photos/${photoId}/persons`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ person_id: personId })
    })
  );
}

export async function deleteGalleryPhotoPerson(photoId: number, personId: number): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(
    await fetch(`/api/gallery/photos/${photoId}/persons/${personId}`, {
      method: "DELETE"
    })
  );
}

export async function addGalleryPhotoTag(photoId: number, payload: { tagId?: number; name?: string }): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(
    await fetch(`/api/gallery/photos/${photoId}/tags`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload.tagId ? { tag_id: payload.tagId } : { name: payload.name })
    })
  );
}

export async function deleteGalleryPhotoTag(photoId: number, tagId: number): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(
    await fetch(`/api/gallery/photos/${photoId}/tags/${tagId}`, {
      method: "DELETE"
    })
  );
}

export type GalleryUploadMetadata = {
  person_names: string[];
  tag_names: string[];
  rich_text?: string;
};

export async function importGalleryPhotos(files: File[], metadata: GalleryUploadMetadata[]): Promise<Task> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.append("metadata_json", JSON.stringify(metadata));
  return parse<Task>(
    await fetch("/api/gallery/photos/import", {
      method: "POST",
      body: form
    })
  );
}

export async function importGalleryRichPhotos(files: File[], metadata: GalleryUploadMetadata[]): Promise<Task> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  form.append("metadata_json", JSON.stringify(metadata));
  return parse<Task>(
    await fetch("/api/gallery/rich-photos/import", {
      method: "POST",
      body: form
    })
  );
}

export async function updateGalleryPhotoRichText(photoId: number, richText: string): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(
    await fetch(`/api/gallery/photos/${photoId}/rich-text`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ rich_text: richText })
    })
  );
}

export async function getTask(taskId: string): Promise<Task> {
  return parse<Task>(await fetch(`/api/tasks/${taskId}`));
}

export async function reRecognizeGalleryPhoto(photoId: number): Promise<GalleryPhotoDetail> {
  return parse<GalleryPhotoDetail>(
    await fetch(`/api/gallery/photos/${photoId}/re-recognize`, {
      method: "POST"
    })
  );
}

export async function reRecognizeUnknownGalleryPhotos(): Promise<{ total: number; succeeded: number; failed: number }> {
  return parse<{ total: number; succeeded: number; failed: number }>(
    await fetch("/api/gallery/photos/re-recognize-unknown", {
      method: "POST"
    })
  );
}

export async function getTagStatistics(isSystem?: boolean): Promise<TagStatistics[]> {
  const url = new URL("/api/statistics/tags", window.location.origin);
  if (typeof isSystem === "boolean") {
    url.searchParams.set("is_system", String(isSystem));
  }
  return parse<TagStatistics[]>(await fetch(url.pathname + url.search));
}

export async function getUploadHistory(
  uploadType?: string,
  limit: number = 50,
  offset: number = 0
): Promise<UploadHistory[]> {
  const url = new URL("/api/statistics/upload-history", window.location.origin);
  if (uploadType) {
    url.searchParams.set("upload_type", uploadType);
  }
  url.searchParams.set("limit", String(limit));
  url.searchParams.set("offset", String(offset));
  return parse<UploadHistory[]>(await fetch(url.pathname + url.search));
}

export async function getPersonStatistics(isUnknown?: boolean): Promise<PersonStatistics[]> {
  const url = new URL("/api/statistics/persons", window.location.origin);
  if (typeof isUnknown === "boolean") {
    url.searchParams.set("is_unknown", String(isUnknown));
  }
  return parse<PersonStatistics[]>(await fetch(url.pathname + url.search));
}

export async function getUploadSummary(): Promise<UploadSummary> {
  return parse<UploadSummary>(await fetch("/api/statistics/upload-summary"));
}

export function getPersonExportUrl(): string {
  return "/api/persons/export";
}

export async function importPersonSamples(file: File): Promise<Task> {
  const formData = new FormData();
  formData.append("file", file);
  return parse<Task>(
    await fetch("/api/persons/import", {
      method: "POST",
      body: formData
    })
  );
}
