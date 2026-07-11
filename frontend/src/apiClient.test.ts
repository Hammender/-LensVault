import { afterEach, describe, expect, it, vi } from "vitest";

import {
  authFetch,
  decorateMediaUrls,
  getAuthToken,
  getSelectedWorkspaceId,
  parseResponse,
  setAuthToken,
  setSelectedWorkspaceId,
  withAccessToken
} from "./apiClient";

function installWindow() {
  const values = new Map<string, string>();
  const fetch = vi.fn();
  Object.assign(globalThis, {
    window: {
      location: { origin: "http://localhost:5173" },
      localStorage: {
        getItem: (key: string) => values.get(key) ?? null,
        setItem: (key: string, value: string) => values.set(key, value),
        removeItem: (key: string) => values.delete(key)
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
  it("adds token and workspace information to requests and media URLs", () => {
    const fetch = installWindow();
    setAuthToken("token");
    setSelectedWorkspaceId(7);
    expect(getAuthToken()).toBe("token");
    expect(getSelectedWorkspaceId()).toBe(7);
    expect(withAccessToken("/api/media/1")).toBe("/api/media/1?access_token=token&workspace_id=7");
    decorateMediaUrls({ thumbnail_url: "/api/media/1" });
    expect(fetch).not.toHaveBeenCalled();
    void authFetch("/api/test");
    expect(fetch.mock.calls[0][1].headers.get("Authorization")).toBe("Bearer token");
    expect(fetch.mock.calls[0][1].headers.get("X-Workspace-Id")).toBe("7");
  });

  it("extracts detail errors and returns decorated JSON", async () => {
    installWindow();
    setAuthToken("token");
    setSelectedWorkspaceId(7);
    const response = new Response(JSON.stringify({ detail: "权限不足" }), { status: 403 });
    await expect(parseResponse(response)).rejects.toThrow("权限不足");
    const success = new Response(JSON.stringify({ original_url: "/api/media/2" }), { status: 200 });
    expect(await parseResponse(success)).toMatchObject({ original_url: "/api/media/2?access_token=token&workspace_id=7" });
  });
});
