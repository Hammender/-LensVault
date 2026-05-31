import type {
  AuthSession,
  BootstrapStatus,
  GalleryPhotoDetail,
  PaginatedGalleryPhotos,
  Person,
  SamplePhoto,
  Tag,
  Task,
  TagStatistics,
  PersonStatistics,
  PaginatedVideos,
  UploadHistory,
  UploadSummary,
  SubtitleJob,
  SubtitleServiceLogs,
  SubtitleServiceStatus,
  EmbeddedSubtitleStream,
  VideoCategoryTag,
  VideoDetail,
  VideoItem,
  VideoPerson,
  VideoSubtitleTrack,
  VideoUploadSession,
  WorkspaceInvitation,
  WorkspaceMember,
  WorkspaceRead
} from "./types";

const jsonHeaders = { "Content-Type": "application/json" };
const authTokenStorageKey = "pictureshow-access-token";
const workspaceStorageKey = "pictureshow-workspace-id";

export function getAuthToken(): string | null {
  return window.localStorage.getItem(authTokenStorageKey);
}

export function setAuthToken(token: string): void {
  window.localStorage.setItem(authTokenStorageKey, token);
}

export function clearAuthToken(): void {
  window.localStorage.removeItem(authTokenStorageKey);
}

export function getSelectedWorkspaceId(): number | null {
  const value = window.localStorage.getItem(workspaceStorageKey);
  return value ? Number(value) : null;
}

export function setSelectedWorkspaceId(workspaceId: number): void {
  window.localStorage.setItem(workspaceStorageKey, String(workspaceId));
}

export function clearSelectedWorkspaceId(): void {
  window.localStorage.removeItem(workspaceStorageKey);
}

function withAccessToken(path: string): string {
  const token = getAuthToken();
  if (!token) {
    return path;
  }
  const url = new URL(path, window.location.origin);
  url.searchParams.set("access_token", token);
  const workspaceId = getSelectedWorkspaceId();
  if (workspaceId) {
    url.searchParams.set("workspace_id", String(workspaceId));
  }
  return url.pathname + url.search;
}

function decorateMediaUrls<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => decorateMediaUrls(item)) as T;
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const record = value as Record<string, unknown>;
  Object.entries(record).forEach(([key, item]) => {
    if (typeof item === "string" && key.endsWith("_url") && item.startsWith("/api/")) {
      record[key] = withAccessToken(item);
      return;
    }
    if (item && typeof item === "object") {
      record[key] = decorateMediaUrls(item);
    }
  });
  return value;
}

function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAuthToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const workspaceId = getSelectedWorkspaceId();
  if (workspaceId) {
    headers.set("X-Workspace-Id", String(workspaceId));
  }
  return window.fetch(input, { ...init, headers });
}

const fetch = authFetch;

async function parse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let errorMessage = text || response.statusText;
    try {
      const json = JSON.parse(text) as { detail?: string };
      if (json && typeof json.detail === "string") {
        errorMessage = json.detail;
      }
    } catch {
      // Not JSON, use fallback text
    }
    throw new Error(errorMessage);
  }
  const data = (await response.json()) as T;
  return decorateMediaUrls(data);
}

export async function getBootstrapStatus(): Promise<BootstrapStatus> {
  return parse<BootstrapStatus>(await fetch("/api/auth/bootstrap-status"));
}

export async function bootstrapAdmin(payload: {
  username: string;
  password: string;
  display_name?: string | null;
  workspace_name?: string | null;
}): Promise<AuthSession> {
  return parse<AuthSession>(
    await fetch("/api/auth/bootstrap", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function login(username: string, password: string): Promise<AuthSession> {
  return parse<AuthSession>(
    await fetch("/api/auth/login", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ username, password })
    })
  );
}

export async function registerAccount(payload: {
  username: string;
  password: string;
  display_name?: string | null;
}): Promise<AuthSession> {
  return parse<AuthSession>(
    await fetch("/api/auth/register", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function getCurrentSession(): Promise<AuthSession> {
  return parse<AuthSession>(await authFetch("/api/auth/me"));
}

export type WorkspacePermissionsPayload = {
  can_add_gallery?: boolean;
  can_delete_gallery?: boolean;
  can_edit_gallery?: boolean;
  can_add_samples?: boolean;
  can_delete_samples?: boolean;
  can_edit_samples?: boolean;
  can_add_videos?: boolean;
  can_delete_videos?: boolean;
  can_edit_videos?: boolean;
};

export async function createWorkspace(name: string): Promise<WorkspaceRead> {
  return parse<WorkspaceRead>(
    await fetch("/api/workspaces", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function listWorkspaceMembers(workspaceId: number): Promise<WorkspaceMember[]> {
  return parse<WorkspaceMember[]>(await fetch(`/api/workspaces/${workspaceId}/members`));
}

export async function updateWorkspaceMember(
  workspaceId: number,
  memberId: number,
  permissions: WorkspacePermissionsPayload
): Promise<WorkspaceMember> {
  return parse<WorkspaceMember>(
    await fetch(`/api/workspaces/${workspaceId}/members/${memberId}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify(permissions)
    })
  );
}

export async function removeWorkspaceMember(workspaceId: number, memberId: number): Promise<void> {
  await parse<{ status: string }>(await fetch(`/api/workspaces/${workspaceId}/members/${memberId}`, { method: "DELETE" }));
}

export async function leaveWorkspace(workspaceId: number): Promise<void> {
  await parse<{ status: string }>(await fetch(`/api/workspaces/${workspaceId}/leave`, { method: "POST" }));
}

export async function inviteWorkspaceMember(
  workspaceId: number,
  username: string,
  permissions: WorkspacePermissionsPayload
): Promise<WorkspaceInvitation> {
  return parse<WorkspaceInvitation>(
    await fetch(`/api/workspaces/${workspaceId}/invitations`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ username, ...permissions })
    })
  );
}

export async function createWorkspaceUser(
  workspaceId: number,
  payload: { username: string; password: string; display_name?: string | null } & WorkspacePermissionsPayload
): Promise<void> {
  await parse<{ id: number }>(
    await fetch(`/api/workspaces/${workspaceId}/users`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function listWorkspaceInvitations(): Promise<WorkspaceInvitation[]> {
  return parse<WorkspaceInvitation[]>(await fetch("/api/workspace-invitations"));
}

export async function acceptWorkspaceInvitation(invitationId: number): Promise<WorkspaceRead> {
  return parse<WorkspaceRead>(await fetch(`/api/workspace-invitations/${invitationId}/accept`, { method: "POST" }));
}

export async function declineWorkspaceInvitation(invitationId: number): Promise<void> {
  await parse<{ status: string }>(await fetch(`/api/workspace-invitations/${invitationId}/decline`, { method: "POST" }));
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

export type GalleryExportScope = "all" | "filtered";

export type GalleryExportOptions = {
  scope: GalleryExportScope;
  personIds?: number[];
  tagIds?: number[];
  excludePersonIds?: number[];
  excludeTagIds?: number[];
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

export function getGalleryExportUrl(options: GalleryExportOptions): string {
  const url = new URL("/api/gallery/photos/export", window.location.origin);
  url.searchParams.set("scope", options.scope);
  options.personIds?.forEach((id) => url.searchParams.append("person_ids", String(id)));
  options.tagIds?.forEach((id) => url.searchParams.append("tag_ids", String(id)));
  options.excludePersonIds?.forEach((id) => url.searchParams.append("exclude_person_ids", String(id)));
  options.excludeTagIds?.forEach((id) => url.searchParams.append("exclude_tag_ids", String(id)));
  return withAccessToken(url.pathname + url.search);
}

export async function importGalleryExportZip(file: File): Promise<Task> {
  const formData = new FormData();
  formData.append("file", file);
  return parse<Task>(
    await fetch("/api/gallery/photos/import-zip", {
      method: "POST",
      body: formData
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

export async function getSubtitleServiceStatus(): Promise<SubtitleServiceStatus> {
  return parse<SubtitleServiceStatus>(await fetch("/api/subtitle-service/status"));
}

export async function startSubtitleService(): Promise<SubtitleServiceStatus> {
  return parse<SubtitleServiceStatus>(
    await fetch("/api/subtitle-service/start", {
      method: "POST"
    })
  );
}

export async function stopSubtitleService(cancelRunning = true): Promise<SubtitleServiceStatus> {
  const url = new URL("/api/subtitle-service/stop", window.location.origin);
  url.searchParams.set("cancel_running", String(cancelRunning));
  return parse<SubtitleServiceStatus>(
    await fetch(url.pathname + url.search, {
      method: "POST"
    })
  );
}

export async function getSubtitleServiceLogs(tail = 200): Promise<SubtitleServiceLogs> {
  const url = new URL("/api/subtitle-service/logs", window.location.origin);
  url.searchParams.set("tail", String(tail));
  return parse<SubtitleServiceLogs>(await fetch(url.pathname + url.search));
}

export async function listSubtitleJobs(): Promise<SubtitleJob[]> {
  return parse<SubtitleJob[]>(await fetch("/api/subtitle-jobs"));
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
  return withAccessToken("/api/persons/export");
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

export async function listVideoCategoryTags(): Promise<VideoCategoryTag[]> {
  return parse<VideoCategoryTag[]>(await fetch("/api/video-category-tags"));
}

export async function createVideoCategoryTag(name: string): Promise<VideoCategoryTag> {
  return parse<VideoCategoryTag>(
    await fetch("/api/video-category-tags", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function listVideoPeople(): Promise<VideoPerson[]> {
  return parse<VideoPerson[]>(await fetch("/api/video-people"));
}

export async function createVideoPerson(name: string, note: string, avatar?: File | null): Promise<VideoPerson> {
  const form = new FormData();
  form.append("name", name);
  form.append("note", note);
  if (avatar) {
    form.append("avatar", avatar);
  }
  return parse<VideoPerson>(
    await fetch("/api/video-people", {
      method: "POST",
      body: form
    })
  );
}

export async function listVideos(
  categoryTagIds: number[],
  personIds: number[],
  query: string,
  offset: number,
  limit: number
): Promise<PaginatedVideos> {
  const url = new URL("/api/videos", window.location.origin);
  categoryTagIds.forEach((id) => url.searchParams.append("category_tag_ids", String(id)));
  personIds.forEach((id) => url.searchParams.append("person_ids", String(id)));
  if (query.trim()) {
    url.searchParams.set("query", query.trim());
  }
  url.searchParams.set("offset", String(offset));
  url.searchParams.set("limit", String(limit));
  return parse<PaginatedVideos>(await fetch(url.pathname + url.search));
}

export async function getVideo(videoId: number): Promise<VideoDetail> {
  return parse<VideoDetail>(await fetch(`/api/videos/${videoId}`));
}

export async function deleteVideo(videoId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/videos/${videoId}`, {
      method: "DELETE"
    })
  );
}

export async function replaceVideoCover(videoId: number, file: File): Promise<VideoDetail> {
  const form = new FormData();
  form.append("file", file);
  return parse<VideoDetail>(
    await fetch(`/api/videos/${videoId}/cover`, {
      method: "PUT",
      body: form
    })
  );
}

export async function createVideoUploadSession(payload: {
  title: string;
  description?: string | null;
  filename: string;
  content_type?: string | null;
  size_bytes: number;
  part_size?: number;
}): Promise<VideoUploadSession> {
  return parse<VideoUploadSession>(
    await fetch("/api/videos/upload-sessions", {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function getVideoUploadSession(sessionId: string): Promise<VideoUploadSession> {
  return parse<VideoUploadSession>(await fetch(`/api/videos/upload-sessions/${sessionId}`));
}

export async function uploadVideoPart(sessionId: string, partIndex: number, blob: Blob, filename: string): Promise<void> {
  const form = new FormData();
  form.append("file", blob, filename);
  await parse<{ session_id: string }>(
    await fetch(`/api/videos/upload-sessions/${sessionId}/parts/${partIndex}`, {
      method: "PUT",
      body: form
    })
  );
}

export async function completeVideoUpload(
  sessionId: string,
  payload: { category_tag_ids: number[]; category_tag_names: string[]; person_ids: number[]; generate_zh_subtitles?: boolean }
): Promise<VideoDetail> {
  return parse<VideoDetail>(
    await fetch(`/api/videos/upload-sessions/${sessionId}/complete`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function generateVideoSubtitles(videoId: number): Promise<VideoSubtitleTrack> {
  return parse<VideoSubtitleTrack>(
    await fetch(`/api/videos/${videoId}/subtitles/generate`, {
      method: "POST"
    })
  );
}

export async function cancelVideoSubtitles(videoId: number, trackId: number): Promise<VideoSubtitleTrack> {
  return parse<VideoSubtitleTrack>(
    await fetch(`/api/videos/${videoId}/subtitles/${trackId}/cancel`, {
      method: "POST"
    })
  );
}

export async function listEmbeddedSubtitleStreams(videoId: number): Promise<EmbeddedSubtitleStream[]> {
  return parse<EmbeddedSubtitleStream[]>(await fetch(`/api/videos/${videoId}/embedded-subtitle-streams`));
}

export async function importSubtitleFromVideo(
  videoId: number,
  payload: { source_video_id: number; stream_index: number; replace?: boolean }
): Promise<VideoSubtitleTrack> {
  return parse<VideoSubtitleTrack>(
    await fetch(`/api/videos/${videoId}/subtitles/import-from-video`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function cancelVideoUpload(sessionId: string): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/videos/upload-sessions/${sessionId}`, {
      method: "DELETE"
    })
  );
}

export async function updateVideo(
  videoId: number,
  payload: { title?: string; description?: string | null }
): Promise<VideoDetail> {
  return parse<VideoDetail>(
    await fetch(`/api/videos/${videoId}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify(payload)
    })
  );
}

export async function addVideoCategoryTag(
  videoId: number,
  payload: { tagId?: number; name?: string }
): Promise<VideoDetail> {
  return parse<VideoDetail>(
    await fetch(`/api/videos/${videoId}/category-tags`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify(payload.tagId ? { tag_id: payload.tagId } : { name: payload.name })
    })
  );
}

export async function removeVideoCategoryTag(videoId: number, tagId: number): Promise<VideoDetail> {
  return parse<VideoDetail>(
    await fetch(`/api/videos/${videoId}/category-tags/${tagId}`, {
      method: "DELETE"
    })
  );
}

export async function addVideoPerson(videoId: number, personId: number): Promise<VideoDetail> {
  return parse<VideoDetail>(
    await fetch(`/api/videos/${videoId}/people`, {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ person_id: personId })
    })
  );
}

export async function removeVideoPerson(videoId: number, personId: number): Promise<VideoDetail> {
  return parse<VideoDetail>(
    await fetch(`/api/videos/${videoId}/people/${personId}`, {
      method: "DELETE"
    })
  );
}

export async function updateVideoCategoryTag(tagId: number, name: string): Promise<VideoCategoryTag> {
  return parse<VideoCategoryTag>(
    await fetch(`/api/video-category-tags/${tagId}`, {
      method: "PATCH",
      headers: jsonHeaders,
      body: JSON.stringify({ name })
    })
  );
}

export async function deleteVideoCategoryTag(tagId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/video-category-tags/${tagId}`, {
      method: "DELETE"
    })
  );
}

export async function updateVideoPerson(
  personId: number,
  name?: string,
  note?: string | null,
  avatar?: File | null
): Promise<VideoPerson> {
  const form = new FormData();
  if (name !== undefined) form.append("name", name);
  if (note !== undefined) form.append("note", note ?? "");
  if (avatar) form.append("avatar", avatar);
  return parse<VideoPerson>(
    await fetch(`/api/video-people/${personId}`, {
      method: "PATCH",
      body: form
    })
  );
}

export async function deleteVideoPerson(personId: number): Promise<void> {
  await parse<{ status: string }>(
    await fetch(`/api/video-people/${personId}`, {
      method: "DELETE"
    })
  );
}
