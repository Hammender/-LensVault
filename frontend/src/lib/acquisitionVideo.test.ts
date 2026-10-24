import { describe, expect, it, vi } from "vitest";
import { formatVideoTime, parseVideoTime, toggleAcquisitionVideoPlayback } from "./acquisitionVideo";

describe("视频精确定位时间", () => {
  it("支持秒数、分秒和跨小时定位", () => {
    expect(parseVideoTime("1.234")).toBe(1.234);
    expect(parseVideoTime("01:23.456")).toBe(83.456);
    expect(parseVideoTime("01:02:03.456")).toBe(3723.456);
    expect(formatVideoTime(3723.456, true)).toBe("01:02:03.456");
  });
  it("拒绝无效或非有限时间", () => {
    for (const value of ["", "-1", "Infinity", "1:60", "1:2:70", "1.2345", "1:2:3:4"]) {
      expect(parseVideoTime(value)).toBeNull();
    }
    expect(formatVideoTime(Number.NaN, true)).toBe("00:00.000");
    expect(formatVideoTime(59.999, true)).toBe("00:59.999");
  });
});

describe("审核视频播放恢复", () => {
  function setup(paused = true) {
    const video = {
      paused, currentTime: 5,
      play: vi.fn(async () => { video.paused = false; }),
      pause: vi.fn(() => { video.paused = true; })
    };
    const options = { clearFrame: vi.fn(), isCurrent: () => true, showIndicator: vi.fn() };
    return { video, options };
  }

  it("从精确帧继续播放前取消定位并清除覆盖层", async () => {
    const { video, options } = setup();
    video.play.mockImplementation(async () => {
      expect(video.currentTime).toBe(12.345);
      expect(options.clearFrame).toHaveBeenCalledOnce();
      video.paused = false;
    });
    await toggleAcquisitionVideoPlayback(video, { ...options, frameTime: 12.345 });
    expect(options.showIndicator.mock.calls).toEqual([["播放"]]);
  });

  it("尚未得到精确帧时也会取消定位，从视频原位置继续", async () => {
    const { video, options } = setup();
    await toggleAcquisitionVideoPlayback(video, options);
    expect(video.currentTime).toBe(5);
    expect(options.clearFrame).toHaveBeenCalledOnce();
    expect(video.play).toHaveBeenCalledOnce();
  });

  it("播放中切到暂停，不触发新的播放或精确帧跳转", async () => {
    const { video, options } = setup(false);
    await toggleAcquisitionVideoPlayback(video, { ...options, frameTime: 12.345 });
    expect(video.pause).toHaveBeenCalledOnce();
    expect(video.play).not.toHaveBeenCalled();
    expect(video.currentTime).toBe(5);
    expect(options.clearFrame).not.toHaveBeenCalled();
    expect(options.showIndicator.mock.calls).toEqual([["暂停"]]);
  });

  it("播放失败给出反馈，不显示播放成功", async () => {
    const { video, options } = setup();
    video.play.mockRejectedValue(new Error("播放被拒绝"));
    await toggleAcquisitionVideoPlayback(video, options);
    expect(options.showIndicator.mock.calls).toEqual([["无法播放，请重试"]]);
  });

  it("快速暂停或切换素材后，旧播放请求完成不会覆盖当前反馈", async () => {
    for (const isCurrent of [true, false]) {
      const { video, options } = setup();
      let resolve!: () => void;
      video.play.mockImplementation(() => new Promise<void>((done) => { resolve = done; }));
      const operation = toggleAcquisitionVideoPlayback(video, { ...options, isCurrent: () => isCurrent });
      if (!isCurrent) video.paused = false;
      resolve();
      await operation;
      expect(options.showIndicator).not.toHaveBeenCalled();
    }
  });

  it("主动暂停引起的 AbortError 不显示播放失败", async () => {
    const { video, options } = setup();
    const cause = new Error("播放已取消");
    cause.name = "AbortError";
    video.play.mockRejectedValue(cause);
    await toggleAcquisitionVideoPlayback(video, options);
    expect(options.showIndicator).not.toHaveBeenCalled();
  });
});
