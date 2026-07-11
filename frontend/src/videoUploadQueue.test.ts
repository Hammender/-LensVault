import { describe, expect, it } from "vitest";

import {
  loadStoredVideoUploadQueue,
  normalizeVideoQueueItem,
  saveStoredVideoUploadQueue,
  videoUploadQueueReducer
} from "./videoUploadQueue";

function storage(): Storage {
  const values = new Map<string, string>();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
    removeItem: (key) => values.delete(key),
    clear: () => values.clear(),
    key: (index) => Array.from(values.keys())[index] ?? null,
    get length() {
      return values.size;
    }
  };
}

describe("video upload queue", () => {
  it("restores interrupted records as needs_file and ignores invalid records", () => {
    const item = normalizeVideoQueueItem({
      id: "demo::1::2",
      filename: "demo.mp4",
      size: 1,
      lastModified: 2,
      uploadedParts: [0],
      totalParts: 2,
      progress: 50,
      status: "uploading"
    });
    expect(item?.status).toBe("needs_file");
    expect(item?.progress).toBe(50);
    expect(normalizeVideoQueueItem({ filename: "missing-id.mp4" })).toBeNull();
  });

  it("persists only incomplete queue records and handles malformed storage", () => {
    const store = storage();
    const item = normalizeVideoQueueItem({ id: "a", filename: "a.mp4", size: 1, lastModified: 1, status: "failed" })!;
    const completed = { ...item, id: "b", status: "completed" as const };
    saveStoredVideoUploadQueue([item, completed], store);
    expect(loadStoredVideoUploadQueue(store).map((entry) => entry.id)).toEqual(["a"]);
    store.setItem("pictureshow-video-upload-queue", "not-json");
    expect(loadStoredVideoUploadQueue(store)).toEqual([]);
  });

  it("applies immutable progress and completion transitions", () => {
    const item = normalizeVideoQueueItem({ id: "a", filename: "a.mp4", size: 1, lastModified: 1 })!;
    const progressed = videoUploadQueueReducer([item], {
      type: "update",
      itemId: "a",
      patch: { status: "uploading", progress: 50 }
    });
    expect(progressed[0]).toMatchObject({ status: "uploading", progress: 50 });
    const completed = videoUploadQueueReducer(progressed, {
      type: "update",
      itemId: "a",
      patch: { status: "completed", progress: 100 }
    });
    expect(videoUploadQueueReducer(completed, { type: "remove_completed" })).toEqual([]);
  });
});
