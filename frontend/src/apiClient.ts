const authTokenStorageKey = "pictureshow-access-token";
const workspaceStorageKey = "pictureshow-workspace-id";

export const jsonHeaders = { "Content-Type": "application/json" };

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

export function withAccessToken(path: string): string {
  const token = getAuthToken();
  if (!token) return path;
  const url = new URL(path, window.location.origin);
  url.searchParams.set("access_token", token);
  const workspaceId = getSelectedWorkspaceId();
  if (workspaceId) url.searchParams.set("workspace_id", String(workspaceId));
  return url.pathname + url.search;
}

export function decorateMediaUrls<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => decorateMediaUrls(item)) as T;
  if (!value || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  Object.entries(record).forEach(([key, item]) => {
    if (typeof item === "string" && key.endsWith("_url") && item.startsWith("/api/")) {
      record[key] = withAccessToken(item);
    } else if (item && typeof item === "object") {
      record[key] = decorateMediaUrls(item);
    }
  });
  return value;
}

export function authFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getAuthToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const workspaceId = getSelectedWorkspaceId();
  if (workspaceId) headers.set("X-Workspace-Id", String(workspaceId));
  return window.fetch(input, { ...init, headers });
}

export async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const text = await response.text();
    let errorMessage = text || response.statusText;
    try {
      const json = JSON.parse(text) as { detail?: string };
      if (json && typeof json.detail === "string") errorMessage = json.detail;
    } catch {
      // Non-JSON errors use the response text.
    }
    throw new Error(errorMessage);
  }
  return decorateMediaUrls((await response.json()) as T);
}
