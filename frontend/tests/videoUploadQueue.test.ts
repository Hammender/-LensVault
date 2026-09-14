import { describe, expect, it } from "vitest";

import {
  loadStoredVideoUploadQueue,
  normalizeVideoQueueItem,
  saveStoredVideoUploadQueue,
  videoUploadQueueReducer
} from "../src/lib/videoUploadQueue";

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

  it("persists only resumable queue records and ignores failed history", () => {
    const store = storage();
    const resumable = normalizeVideoQueueItem({
      id: "a",
      filename: "a.mp4",
      size: 1,
      lastModified: 1,
      uploadedParts: [0],
      totalParts: 2,
      progress: 50,
      status: "uploading"
    })!;
    const failed = { ...resumable, id: "b", status: "failed" as const, error: "视频库已存在相同文件" };
    const completed = { ...resumable, id: "c", status: "completed" as const };
    saveStoredVideoUploadQueue([resumable, failed, completed], store);
    expect(loadStoredVideoUploadQueue(store).map((entry) => entry.id)).toEqual(["a"]);
    store.setItem("pictureshow-video-upload-queue", JSON.stringify([failed]));
    expect(loadStoredVideoUploadQueue(store)).toEqual([]);
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
