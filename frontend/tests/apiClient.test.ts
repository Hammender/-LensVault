import { afterEach, describe, expect, it, vi } from "vitest";

import {
  AUTH_EXPIRED_EVENT,
  AuthExpiredError,
  authFetch,
  decorateMediaUrls,
  formatApiErrorDetail,
  getAuthToken,
  getSelectedWorkspaceId,
  parseResponse,
  setAuthToken,
  setSelectedWorkspaceId,
  withWorkspaceContext
} from "../src/lib/apiClient";

function installWindow() {
  const values = new Map<string, string>();
  const fetch = vi.fn();
  const listeners = new Map<string, Set<EventListener>>();
  Object.assign(globalThis, {
    window: {
      location: { origin: "http://localhost:5173" },
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key)
      },
      addEventListener: (type: string, listener: EventListener) => {
        const set = listeners.get(type) ?? new Set();
        set.add(listener);
        listeners.set(type, set);
      },
      removeEventListener: (type: string, listener: EventListener) => {
        listeners.get(type)?.delete(listener);
      },
      dispatchEvent: (event: Event) => {
        listeners.get(event.type)?.forEach((listener) => listener(event));
        return true;
      },
      fetch
    }
  });
  return fetch;
}

afterEach(() => {
  delete (globalThis as { window?: unknown }).window;
  vi.restoreAllMocks();
});

describe("shared API client", () => {
  it("adds authentication to requests without exposing tokens in media URLs", () => {
    const fetch = installWindow();
    setAuthToken("token");
    setSelectedWorkspaceId(7);
    expect(getAuthToken()).toBe("token");
    expect(getSelectedWorkspaceId()).toBe(7);
    expect(withWorkspaceContext("/api/media/1")).toBe("/api/media/1?workspace_id=7");
    decorateMediaUrls({ thumbnail_url: "/api/media/1" });
    expect(fetch).not.toHaveBeenCalled();
    void authFetch("/api/test");
    expect(fetch.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer token");
    expect(fetch.mock.calls[0][1].headers.get("X-Workspace-Id")).toBe("7");
    expect(fetch.mock.calls[0][1].credentials).toBe("include");
  });

  it("extracts detail errors and returns decorated JSON", async () => {
    installWindow();
    setAuthToken("token");
    setSelectedWorkspaceId(7);
    const response = new Response(JSON.stringify({ detail: "权限不足" }), { status: 403 });
    await expect(parseResponse(response)).rejects.toThrow("权限不足");
    const success = new Response(JSON.stringify({ original_url: "/api/media/2" }), { status: 200 });
    expect(await parseResponse(success)).toMatchObject({ original_url: "/api/media/2?workspace_id=7" });
  });

  it("joins FastAPI validation detail arrays", () => {
    expect(formatApiErrorDetail(JSON.stringify({ detail: [{ msg: "标题不能为空" }, { msg: "文件过大" }] }))).toBe(
      "标题不能为空；文件过大"
    );
  });

  it("clears the token and notifies on 401", async () => {
    installWindow();
    setAuthToken("token");
    const expired = vi.fn();
    window.addEventListener(AUTH_EXPIRED_EVENT, expired);
    const response = new Response(JSON.stringify({ detail: "登录已过期，请重新登录" }), { status: 401 });
    await expect(parseResponse(response)).rejects.toBeInstanceOf(AuthExpiredError);
    expect(getAuthToken()).toBeNull();
    expect(expired).toHaveBeenCalledTimes(1);
  });
});
