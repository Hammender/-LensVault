import { describe, expect, it, vi } from "vitest";

import { releaseHtmlVideo } from "../src/lib/htmlVideo";

describe("releaseHtmlVideo", () => {
  it("ignores a missing video element", () => {
    expect(() => releaseHtmlVideo(null)).not.toThrow();
  });

  it("pauses, clears the source, and reloads the element", () => {
    const video = {
      pause: vi.fn(),
      removeAttribute: vi.fn(),
      load: vi.fn()
    } as unknown as HTMLVideoElement;

    releaseHtmlVideo(video);

    expect(video.pause).toHaveBeenCalledTimes(1);
    expect(video.removeAttribute).toHaveBeenCalledWith("src");
    expect(video.load).toHaveBeenCalledTimes(1);
  });
});
