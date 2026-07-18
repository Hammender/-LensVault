import { describe, expect, it } from "vitest";

import { pageFromHash } from "../src/routing";

describe("pageFromHash", () => {
  it.each([
    ["", "home"],
    ["#/", "home"],
    ["#/gallery", "gallery"],
    ["#people", "people"],
    ["#/upload", "upload"],
    ["#/videos", "videos"],
    ["#/statistics", "statistics"],
    ["#/video-play/42", "video-play"],
    ["#/unknown", "home"]
  ])("maps %s to %s", (hash, expected) => {
    expect(pageFromHash(hash)).toBe(expected);
  });
});
