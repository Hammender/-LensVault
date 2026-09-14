import type { SubtitleJob, SubtitleServiceLogs, SubtitleServiceStatus } from "../types";
import { authFetch, parseResponse } from "../lib/apiClient";

export async function getSubtitleServiceStatus(): Promise<SubtitleServiceStatus> {
  return parseResponse<SubtitleServiceStatus>(await authFetch("/api/subtitle-service/status"));
}

export async function startSubtitleService(): Promise<SubtitleServiceStatus> {
  return parseResponse<SubtitleServiceStatus>(
    await authFetch("/api/subtitle-service/start", {
      method: "POST"
    })
  );
}

export async function stopSubtitleService(cancelRunning = true): Promise<SubtitleServiceStatus> {
  const url = new URL("/api/subtitle-service/stop", window.location.origin);
  url.searchParams.set("cancel_running", String(cancelRunning));
  return parseResponse<SubtitleServiceStatus>(
    await authFetch(url.pathname + url.search, {
      method: "POST"
    })
  );
}

export async function getSubtitleServiceLogs(tail = 200): Promise<SubtitleServiceLogs> {
  const url = new URL("/api/subtitle-service/logs", window.location.origin);
  url.searchParams.set("tail", String(tail));
  return parseResponse<SubtitleServiceLogs>(await authFetch(url.pathname + url.search));
}

export async function listSubtitleJobs(): Promise<SubtitleJob[]> {
  return parseResponse<SubtitleJob[]>(await authFetch("/api/subtitle-jobs"));
}
