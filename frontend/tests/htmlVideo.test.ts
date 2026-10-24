import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { htmlVideoHasAddress, releaseHtmlVideo, waitForHtmlVideoRelease } from "../src/lib/htmlVideo";

type FakeVideo = HTMLVideoElement & { emit: (type: string) => void };

function fakeVideo(options?: { src?: string | null; currentSrc?: string; networkState?: number }): FakeVideo {
  const attributes = new Map<string, string>();
  if (options?.src) attributes.set("src", options.src);
  const listeners = new Map<string, Set<() => void>>();
  const video = {
    currentSrc: options?.currentSrc ?? "",
    networkState: options?.networkState ?? 2,
    getAttribute(name: string) {
      return attributes.has(name) ? attributes.get(name)! : null;
    },
    addEventListener(type: string, listener: () => void) {
      const group = listeners.get(type) ?? new Set<() => void>();
      group.add(listener);
      listeners.set(type, group);
    },
    removeEventListener(type: string, listener: () => void) {
      listeners.get(type)?.delete(listener);
    },
    emit(type: string) {
      for (const listener of [...(listeners.get(type) ?? [])]) listener();
    }
  };
  return video as unknown as FakeVideo;
}

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

describe("htmlVideoHasAddress", () => {
  it("is false when the src attribute and currentSrc are both empty", () => {
    expect(htmlVideoHasAddress(fakeVideo())).toBe(false);
  });

  it("is true when the src attribute is set", () => {
    expect(htmlVideoHasAddress(fakeVideo({ src: "clip.mp4" }))).toBe(true);
  });

  it("is true when currentSrc is set without a src attribute", () => {
    expect(htmlVideoHasAddress(fakeVideo({ currentSrc: "https://example.test/clip.mp4" }))).toBe(true);
  });
});

describe("waitForHtmlVideoRelease", () => {
  beforeEach(() => {
    vi.stubGlobal("HTMLMediaElement", { NETWORK_EMPTY: 0 });
    vi.stubGlobal("window", {
      setTimeout: (handler: TimerHandler, timeout?: number) => setTimeout(handler, timeout),
      clearTimeout: (handle: ReturnType<typeof setTimeout>) => clearTimeout(handle)
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("resolves immediately for a missing video element", async () => {
    await expect(waitForHtmlVideoRelease(null)).resolves.toBeUndefined();
  });

  it("resolves when emptied is dispatched", async () => {
    const video = fakeVideo({ src: "clip.mp4" });
    let settled = false;
    const pending = waitForHtmlVideoRelease(video, 500).then(() => {
      settled = true;
    });
    await Promise.resolve();
    expect(settled).toBe(false);
    video.emit("emptied");
    await pending;
    expect(settled).toBe(true);
  });

  it("resolves when abort is dispatched", async () => {
    const video = fakeVideo({ src: "clip.mp4" });
    const pending = waitForHtmlVideoRelease(video, 500);
    video.emit("abort");
    await expect(pending).resolves.toBeUndefined();
  });

  it("resolves after a short timeout when no release event arrives", async () => {
    const video = fakeVideo({ src: "clip.mp4" });
    const started = Date.now();
    await waitForHtmlVideoRelease(video, 20);
    const elapsed = Date.now() - started;
    expect(elapsed).toBeGreaterThanOrEqual(15);
    expect(elapsed).toBeLessThan(400);
  });

  it("resolves on a microtask when the element is already empty and has no src", async () => {
    const video = fakeVideo({ networkState: 0 });
    let settled = false;
    const pending = waitForHtmlVideoRelease(video, 800).then(() => {
      settled = true;
    });
    expect(settled).toBe(false);
    await Promise.resolve();
    await Promise.resolve();
    expect(settled).toBe(true);
    await pending;
  });
});
