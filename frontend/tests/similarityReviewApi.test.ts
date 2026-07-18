import { afterEach, describe, expect, it, vi } from "vitest";

import { updateGallerySimilarityGroup } from "../src/api";

function installWindow() {
  const fetch = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(JSON.stringify({
    id: 9,
    ordinal: 2,
    tier: "near_duplicate",
    review_status: "dismissed",
    min_score: 0.96,
    average_score: 0.98,
    people: [],
    members: []
  }), { status: 200 }));
  Object.assign(globalThis, {
    window: {
      location: { origin: "http://localhost:5173" },
      localStorage: {
        getItem: () => null,
        setItem: () => undefined,
        removeItem: () => undefined
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

describe("similarity review API", () => {
  it("persists a dismissed group with PATCH", async () => {
    const fetch = installWindow();

    const result = await updateGallerySimilarityGroup("scan-1", 9, "dismissed");

    expect(result.review_status).toBe("dismissed");
    expect(fetch).toHaveBeenCalledOnce();
    expect(fetch.mock.calls[0][0]).toBe("/api/gallery/similarity-scans/scan-1/groups/9");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "PATCH",
      body: JSON.stringify({ review_status: "dismissed" })
    });
  });
});
