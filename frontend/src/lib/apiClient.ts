const authTokenStorageKey = "pictureshow-access-token";
const workspaceStorageKey = "pictureshow-workspace-id";

export const jsonHeaders = { "Content-Type": "application/json" };
export const AUTH_EXPIRED_EVENT = "pictureshow-auth-expired";

export class AuthExpiredError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthExpiredError";
  }
}

export function formatApiErrorDetail(text: string, fallback = "请求失败"): string {
  if (!text) {
    return fallback;
  }
  try {
    const json = JSON.parse(text) as { detail?: unknown };
    if (typeof json.detail === "string" && json.detail.trim()) {
      return json.detail;
    }
    if (Array.isArray(json.detail)) {
      const parts = json.detail
        .map((item) => {
          if (typeof item === "string") {
            return item;
          }
          if (item && typeof item === "object" && "msg" in item) {
            const message = (item as { msg?: unknown }).msg;
            return typeof message === "string" ? message : null;
          }
          return null;
        })
        .filter((item): item is string => Boolean(item && item.trim()));
      if (parts.length > 0) {
        return parts.join("；");
      }
    }
  } catch {
    // Non-JSON errors use the response text.
  }
  return text;
}

function notifyAuthExpired(): void {
  clearAuthToken();
  if (typeof window !== "undefined" && typeof window.dispatchEvent === "function") {
    window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT));
  }
}

export async function rejectHttpError(response: Response, fallback = "请求失败"): Promise<never> {
  const text = await response.text();
  const message = formatApiErrorDetail(text, fallback || response.statusText || "请求失败");
  if (response.status === 401) {
    notifyAuthExpired();
    throw new AuthExpiredError(message);
  }
  throw new Error(message);
}

export async function parseBlobResponse(
  response: Response,
  fallbackFilename: string,
  fallbackError = "下载失败。"
): Promise<{ blob: Blob; filename: string }> {
  if (!response.ok) {
    await rejectHttpError(response, fallbackError);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] ?? fallbackFilename;
  return { blob: await response.blob(), filename };
}

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

export function withWorkspaceContext(path: string): string {
  const workspaceId = getSelectedWorkspaceId();
  if (!workspaceId) return path;
  const url = new URL(path, window.location.origin);
  url.searchParams.set("workspace_id", String(workspaceId));
  return url.pathname + url.search;
}

export function decorateMediaUrls<T>(value: T): T {
  if (Array.isArray(value)) return value.map((item) => decorateMediaUrls(item)) as T;
  if (!value || typeof value !== "object") return value;
  const record = value as Record<string, unknown>;
  Object.entries(record).forEach(([key, item]) => {
    if (typeof item === "string" && key.endsWith("_url") && item.startsWith("/api/")) {
      record[key] = withWorkspaceContext(item);
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
  return window.fetch(input, { ...init, headers, credentials: init.credentials ?? "include" });
}

export async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    await rejectHttpError(response, response.statusText || "请求失败");
  }
  return decorateMediaUrls((await response.json()) as T);
}
