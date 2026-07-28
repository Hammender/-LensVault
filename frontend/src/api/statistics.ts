import type { PersonStatistics, TagStatistics, UploadHistory, UploadSummary } from "../types";
import { authFetch, parseResponse } from "../apiClient";

export async function getTagStatistics(isSystem?: boolean): Promise<TagStatistics[]> {
  const url = new URL("/api/statistics/tags", window.location.origin);
  if (typeof isSystem === "boolean") {
    url.searchParams.set("is_system", String(isSystem));
  }
  return parseResponse<TagStatistics[]>(await authFetch(url.pathname + url.search));
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
  return parseResponse<UploadHistory[]>(await authFetch(url.pathname + url.search));
}

export async function getPersonStatistics(isUnknown?: boolean): Promise<PersonStatistics[]> {
  const url = new URL("/api/statistics/persons", window.location.origin);
  if (typeof isUnknown === "boolean") {
    url.searchParams.set("is_unknown", String(isUnknown));
  }
  return parseResponse<PersonStatistics[]>(await authFetch(url.pathname + url.search));
}

export async function getUploadSummary(): Promise<UploadSummary> {
  return parseResponse<UploadSummary>(await authFetch("/api/statistics/upload-summary"));
}
