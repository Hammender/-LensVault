import type {
  PaginatedVideos,
  VideoCategoryTag,
  VideoDetail,
  VideoPerson,
  VideoPlaybackDiagnostics,
  VideoSubtitleTrack,
  VideoUploadSession
} from "../types";
import { authFetch, jsonHeaders, parseResponse } from "../lib/apiClient";

export async function listVideoCategoryTags(): Promise<VideoCategoryTag[]> {
  return parseResponse<VideoCategoryTag[]>(await authFetch("/api/video-category-tags"));
}

export async function createVideoCategoryTag(name: string): Promise<VideoCategoryTag> {
  return parseResponse<VideoCategoryTag>(await authFetch("/api/video-category-tags", { method: "POST", headers: jsonHeaders, body: JSON.stringify({ name }) }));
}

export async function updateVideoCategoryTag(tagId: number, name: string): Promise<VideoCategoryTag> {
  return parseResponse<VideoCategoryTag>(await authFetch(`/api/video-category-tags/${tagId}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify({ name }) }));
}

export async function deleteVideoCategoryTag(tagId: number): Promise<void> {
  await parseResponse<{ status: string }>(await authFetch(`/api/video-category-tags/${tagId}`, { method: "DELETE" }));
}

export async function listVideoPeople(): Promise<VideoPerson[]> {
  return parseResponse<VideoPerson[]>(await authFetch("/api/video-people"));
}

export async function createVideoPerson(name: string, note: string, avatar?: File | null): Promise<VideoPerson> {
  const form = new FormData();
  form.append("name", name);
  form.append("note", note);
  if (avatar) form.append("avatar", avatar);
  return parseResponse<VideoPerson>(await authFetch("/api/video-people", { method: "POST", body: form }));
}

export async function updateVideoPerson(personId: number, name?: string, note?: string | null, avatar?: File | null): Promise<VideoPerson> {
  const form = new FormData();
  if (name !== undefined) form.append("name", name);
  if (note !== undefined) form.append("note", note ?? "");
  if (avatar) form.append("avatar", avatar);
  return parseResponse<VideoPerson>(await authFetch(`/api/video-people/${personId}`, { method: "PATCH", body: form }));
}

export async function deleteVideoPerson(personId: number): Promise<void> {
  await parseResponse<{ status: string }>(await authFetch(`/api/video-people/${personId}`, { method: "DELETE" }));
}

export async function listVideos(categoryTagIds: number[], personIds: number[], query: string, offset: number, limit: number, videoType?: "short" | "long" | null): Promise<PaginatedVideos> {
  const url = new URL("/api/videos", window.location.origin);
  categoryTagIds.forEach((id) => url.searchParams.append("category_tag_ids", String(id)));
  personIds.forEach((id) => url.searchParams.append("person_ids", String(id)));
  if (query.trim()) url.searchParams.set("query", query.trim());
  if (videoType) url.searchParams.set("video_type", videoType);
  url.searchParams.set("offset", String(offset));
  url.searchParams.set("limit", String(limit));
  return parseResponse<PaginatedVideos>(await authFetch(url.pathname + url.search));
}

export async function getVideo(videoId: number): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}`)); }
export async function getVideoPlaybackDiagnostics(videoId: number): Promise<VideoPlaybackDiagnostics> { return parseResponse<VideoPlaybackDiagnostics>(await authFetch(`/api/videos/${videoId}/playback-diagnostics`)); }
export async function optimizeVideoPlayback(videoId: number): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}/optimize-playback`, { method: "POST" })); }
export async function deleteVideo(videoId: number): Promise<void> { await parseResponse<{ status: string }>(await authFetch(`/api/videos/${videoId}`, { method: "DELETE" })); }

export async function replaceVideoCover(videoId: number, file: File): Promise<VideoDetail> {
  const form = new FormData(); form.append("file", file);
  return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}/cover`, { method: "PUT", body: form }));
}

export async function createVideoUploadSession(payload: { title: string; description?: string | null; filename: string; content_type?: string | null; size_bytes: number; part_size?: number }): Promise<VideoUploadSession> {
  return parseResponse<VideoUploadSession>(await authFetch("/api/videos/upload-sessions", { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) }));
}

export async function getVideoUploadSession(sessionId: string): Promise<VideoUploadSession> { return parseResponse<VideoUploadSession>(await authFetch(`/api/videos/upload-sessions/${sessionId}`)); }
export async function uploadVideoPart(sessionId: string, partIndex: number, blob: Blob, filename: string): Promise<void> { const form = new FormData(); form.append("file", blob, filename); await parseResponse<{ session_id: string }>(await authFetch(`/api/videos/upload-sessions/${sessionId}/parts/${partIndex}`, { method: "PUT", body: form })); }
export async function completeVideoUpload(sessionId: string, payload: { category_tag_ids: number[]; category_tag_names: string[]; person_ids: number[]; generate_zh_subtitles?: boolean; video_type?: "short" | "long" | null }): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/upload-sessions/${sessionId}/complete`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload) })); }
export async function cancelVideoUpload(sessionId: string): Promise<void> { await parseResponse<{ status: string }>(await authFetch(`/api/videos/upload-sessions/${sessionId}`, { method: "DELETE" })); }
export async function updateVideo(videoId: number, payload: { title?: string; description?: string | null; video_type?: "short" | "long" }): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}`, { method: "PATCH", headers: jsonHeaders, body: JSON.stringify(payload) })); }
export async function generateVideoSubtitles(videoId: number): Promise<VideoSubtitleTrack> { return parseResponse<VideoSubtitleTrack>(await authFetch(`/api/videos/${videoId}/subtitles/generate`, { method: "POST" })); }
export async function cancelVideoSubtitles(videoId: number, trackId: number): Promise<VideoSubtitleTrack> { return parseResponse<VideoSubtitleTrack>(await authFetch(`/api/videos/${videoId}/subtitles/${trackId}/cancel`, { method: "POST" })); }
export async function addVideoCategoryTag(videoId: number, payload: { tagId?: number; name?: string }): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}/category-tags`, { method: "POST", headers: jsonHeaders, body: JSON.stringify(payload.tagId ? { tag_id: payload.tagId } : { name: payload.name }) })); }
export async function removeVideoCategoryTag(videoId: number, tagId: number): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}/category-tags/${tagId}`, { method: "DELETE" })); }
export async function addVideoPerson(videoId: number, personId: number): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}/people`, { method: "POST", headers: jsonHeaders, body: JSON.stringify({ person_id: personId }) })); }
export async function removeVideoPerson(videoId: number, personId: number): Promise<VideoDetail> { return parseResponse<VideoDetail>(await authFetch(`/api/videos/${videoId}/people/${personId}`, { method: "DELETE" })); }
