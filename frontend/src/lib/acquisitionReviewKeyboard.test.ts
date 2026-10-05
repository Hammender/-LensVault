import { describe, expect, it, vi } from "vitest";

import { handleAcquisitionLightboxShortcut } from "./acquisitionReview";

type ShortcutEvent = Parameters<typeof handleAcquisitionLightboxShortcut>[0];

function keyEvent(key: string, overrides: Partial<ShortcutEvent> = {}) {
  return {
    key,
    repeat: false,
    defaultPrevented: false,
    ctrlKey: false,
    metaKey: false,
    altKey: false,
    preventDefault: vi.fn(),
    ...overrides
  };
}

describe("采集灯箱键盘选择", () => {
  it.each([" ", "Enter"])("按住 %j 只切换一次，松开后再次按下才切换回来", (key) => {
    let selected = false;
    const onToggleSelect = vi.fn(() => { selected = !selected; });
    const actions = { onToggleSelect };

    handleAcquisitionLightboxShortcut(keyEvent(key), "image", actions);
    for (let index = 0; index < 3; index += 1) {
      const repeated = keyEvent(key, { repeat: true });
      expect(handleAcquisitionLightboxShortcut(repeated, "image", actions)).toBe(true);
      expect(repeated.preventDefault).toHaveBeenCalledOnce();
    }

    expect(selected).toBe(true);
    expect(onToggleSelect).toHaveBeenCalledOnce();
    handleAcquisitionLightboxShortcut(keyEvent(key), "image", actions);
    expect(selected).toBe(false);
    expect(onToggleSelect).toHaveBeenCalledTimes(2);
  });

  it("视频空格保留给播放暂停，Enter 仍可选择视频", () => {
    const onToggleSelect = vi.fn();
    const space = keyEvent(" ");

    expect(handleAcquisitionLightboxShortcut(space, "video", { onToggleSelect })).toBe(false);
    expect(space.preventDefault).not.toHaveBeenCalled();
    expect(onToggleSelect).not.toHaveBeenCalled();
    handleAcquisitionLightboxShortcut(keyEvent("Enter"), "video", { onToggleSelect });
    expect(onToggleSelect).toHaveBeenCalledOnce();
  });

  it.each([
    { defaultPrevented: true },
    { ctrlKey: true },
    { metaKey: true },
    { altKey: true }
  ])("已处理或带组合键的事件不触发选择：%j", (overrides) => {
    const event = keyEvent(" ", overrides);
    const onToggleSelect = vi.fn();

    expect(handleAcquisitionLightboxShortcut(event, "image", { onToggleSelect })).toBe(false);
    expect(onToggleSelect).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("按住 Delete 不会反复发起丢弃，没有丢弃权限时也不发起", () => {
    const onToggleSelect = vi.fn();
    const onReject = vi.fn();

    handleAcquisitionLightboxShortcut(keyEvent("Delete"), "image", { onToggleSelect, onReject });
    handleAcquisitionLightboxShortcut(keyEvent("Delete", { repeat: true }), "image", { onToggleSelect, onReject });
    expect(onReject).toHaveBeenCalledOnce();
    expect(onToggleSelect).not.toHaveBeenCalled();
    const withoutPermission = keyEvent("Delete");
    expect(handleAcquisitionLightboxShortcut(withoutPermission, "image", { onToggleSelect })).toBe(false);
    expect(withoutPermission.preventDefault).not.toHaveBeenCalled();
  });
});
