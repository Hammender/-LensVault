import type { Cluster, PaginatedPhotos, Person, PhotoDetail, Task } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || response.statusText);
  }
  return response.json() as Promise<T>;
}

export async function listPersons(): Promise<Person[]> {
  return parse<Person[]>(await fetch("/api/persons"));
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

export async function addSamples(personId: number, files: File[]): Promise<Person> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return parse<Person>(
    await fetch(`/api/persons/${personId}/samples`, {
      method: "POST",
      body: form
    })
  );
}

export async function importPhotos(files: File[]): Promise<Task> {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  return parse<Task>(
    await fetch("/api/photos/import", {
      method: "POST",
      body: form
    })
  );
}

export async function getTask(taskId: string): Promise<Task> {
  return parse<Task>(await fetch(`/api/tasks/${taskId}`));
}

export async function listPhotos(personIds: number[], offset: number, limit: number): Promise<PaginatedPhotos> {
  const url = new URL("/api/photos", window.location.origin);
  personIds.forEach((id) => url.searchParams.append("person_ids", String(id)));
  url.searchParams.set("offset", String(offset));
  url.searchParams.set("limit", String(limit));
  return parse<PaginatedPhotos>(await fetch(url.pathname + url.search));
}

export async function getPhoto(photoId: number): Promise<PhotoDetail> {
  return parse<PhotoDetail>(await fetch(`/api/photos/${photoId}`));
}

export async function listClusters(): Promise<Cluster[]> {
  return parse<Cluster[]>(await fetch("/api/clusters"));
}

export async function assignCluster(clusterKey: string, personName: string): Promise<Person> {
  return parse<Person>(
    await fetch(`/api/clusters/${clusterKey}/assign`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ person_name: personName })
    })
  );
}

export async function removePhotoTag(photoId: number, personId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/photos/${photoId}/tags/${personId}`, {
      method: "DELETE"
    })
  );
}

export async function reprocessPhoto(photoId: number): Promise<PhotoDetail> {
  return parse<PhotoDetail>(
    await fetch(`/api/photos/${photoId}/reprocess`, {
      method: "POST"
    })
  );
}
