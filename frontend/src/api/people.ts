import type { Person, SamplePhoto, Tag, Task } from "../types";
import { authFetch, jsonHeaders, parseBlobResponse, parseResponse } from "../lib/apiClient";

export async function listPersons(isUnknown?: boolean): Promise<Person[]> {
  const url = new URL("/api/persons", window.location.origin);
  if (typeof isUnknown === "boolean") {
    url.searchParams.set("is_unknown", String(isUnknown));
  }
  return parseResponse<Person[]>(await authFetch(url.pathname + url.search));
}

export async function createPerson(name: string, note?: string): Promise<Person> {
  return parseResponse<Person>(
    await authFetch("/api/persons", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name, note: note || null })
    })
  );
}

export async function renamePerson(personId: number, name: string): Promise<Person> {
  return parseResponse<Person>(
    await authFetch(`/api/persons/${personId}/rename`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function deletePerson(personId: number): Promise<void> {
  await parseResponse<{ status: string }>(
    await authFetch(`/api/persons/${personId}`, {
      method: "DELETE"
    })
  );
}

export async function batchDeletePersons(personIds: number[]): Promise<number> {
  const response = await parseResponse<{ deleted: number }>(
    await authFetch("/api/persons/batch-delete", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ person_ids: personIds })
    })
  );
  return response.deleted;
}

export async function listPersonSamples(personId: number): Promise<SamplePhoto[]> {
  return parseResponse<SamplePhoto[]>(await authFetch(`/api/persons/${personId}/samples`));
}

export async function addPersonSamples(personId: number, files: File[]): Promise<SamplePhoto[]> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return parseResponse<SamplePhoto[]>(
    await authFetch(`/api/persons/${personId}/samples`, {
      method: "POST",
      body: form
    })
  );
}

export async function listPersonTags(personId: number): Promise<Tag[]> {
  return parseResponse<Tag[]>(await authFetch(`/api/persons/${personId}/tags`));
}

export async function bindPersonTag(personId: number, payload: { tagId?: number; name?: string }): Promise<Tag[]> {
  return parseResponse<Tag[]>(
    await authFetch(`/api/persons/${personId}/tags`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload.tagId ? { tag_id: payload.tagId } : { name: payload.name })
    })
  );
}

export async function unbindPersonTag(personId: number, tagId: number): Promise<Tag[]> {
  return parseResponse<Tag[]>(
    await authFetch(`/api/persons/${personId}/tags/${tagId}`, {
      method: "DELETE"
    })
  );
}

export async function deletePersonSample(personId: number, samplePhotoId: number): Promise<void> {
  await parseResponse<{ status: string }>(
    await authFetch(`/api/persons/${personId}/samples/${samplePhotoId}`, {
      method: "DELETE"
    })
  );
}

export async function listTags(): Promise<Tag[]> {
  return parseResponse<Tag[]>(await authFetch("/api/tags"));
}

export async function createTag(name: string): Promise<Tag> {
  return parseResponse<Tag>(
    await authFetch("/api/tags", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function downloadPersonExport(): Promise<{ blob: Blob; filename: string }> {
  return parseBlobResponse(
    await authFetch("/api/persons/export"),
    "person_samples.zip",
    "导出样本库失败。"
  );
}

export async function importPersonSamples(file: File): Promise<Task> {
  const formData = new FormData();
  formData.append("file", file);
  return parseResponse<Task>(
    await authFetch("/api/persons/import", {
      method: "POST",
      body: formData
    })
  );
}
