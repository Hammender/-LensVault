import { describe, expect, it, vi } from "vitest";

import { handleAcquisitionLightboxShortcut } from "./acquisitionReview";
import { getAcquisitionReviewShortcuts, handleAcquisitionReviewKeyDown, type AcquisitionReviewAction } from "./acquisitionReviewKeyboard";

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

describe("待审核灯箱键盘操作", () => {
  function press(key: string, options: {
    isVideo?: boolean; editing?: boolean; range?: boolean; blocked?: boolean;
    repeat?: boolean; ctrlKey?: boolean; metaKey?: boolean; altKey?: boolean;
    shiftKey?: boolean; isComposing?: boolean; defaultPrevented?: boolean;
  } = {}) {
    const event = { ...keyEvent(key), shiftKey: false, isComposing: false, ...options };
    const onAction = vi.fn<(action: AcquisitionReviewAction) => void>();
    const handled = handleAcquisitionReviewKeyDown(event, {
      isVideo: options.isVideo ?? true,
      editing: options.editing ?? false,
      range: options.range ?? false,
      blocked: options.blocked ?? false,
      onAction
    });
    return { event, onAction, handled };
  }

  it.each([false, true])("X 勾选与空格播放分开，Enter 保留原生行为：视频=%s", (isVideo) => {
    const select = press("X", { isVideo });
    expect(select.onAction.mock.calls).toEqual([["select"]]);
    expect(select.event.preventDefault).toHaveBeenCalledOnce();
    const space = press(" ", { isVideo });
    expect(space.onAction.mock.calls).toEqual(isVideo ? [["play"]] : []);
    expect(press("Enter", { isVideo }).onAction).not.toHaveBeenCalled();
  });

  it("按钮或滑块保留焦点不改变空格、X 的含义；滑块左右键仍交给原生控件", () => {
    for (const range of [false, true]) {
      expect(press(" ", { range }).onAction.mock.calls).toEqual([["play"]]);
      expect(press("x", { range }).onAction.mock.calls).toEqual([["select"]]);
    }
    const arrow = press("ArrowRight", { range: true });
    expect(arrow.handled).toBe(true);
    expect(arrow.onAction).not.toHaveBeenCalled();
    expect(arrow.event.preventDefault).not.toHaveBeenCalled();
  });

  it("左右键只切素材，J/L 只调进度；移除重复别名", () => {
    expect(press("ArrowLeft").onAction.mock.calls).toEqual([["previous"]]);
    expect(press("ArrowRight").onAction.mock.calls).toEqual([["next"]]);
    expect(press("j").onAction.mock.calls).toEqual([["seek_back"]]);
    expect(press("L").onAction.mock.calls).toEqual([["seek_forward"]]);
    for (const key of ["ArrowLeft", "ArrowRight", "PageUp", "PageDown"]) {
      expect(press(key, { shiftKey: true }).onAction).not.toHaveBeenCalled();
    }
  });

  it.each([" ", "x", "ArrowLeft", "ArrowRight", ",", ".", "s", "m", "f", "Delete"])("长按 %j 不反复触发动作，也不落入默认灯箱或按钮操作", (key) => {
    const result = press(key, { repeat: true });
    expect(result.handled).toBe(true);
    expect(result.event.preventDefault).toHaveBeenCalledOnce();
    expect(result.onAction).not.toHaveBeenCalled();
  });

  it("长按 J/L 可以持续调整视频进度", () => {
    expect(press("j", { repeat: true }).onAction.mock.calls).toEqual([["seek_back"]]);
    expect(press("l", { repeat: true }).onAction.mock.calls).toEqual([["seek_forward"]]);
  });

  it.each([
    { editing: true }, { blocked: true }, { isComposing: true },
    { ctrlKey: true }, { metaKey: true }, { altKey: true }, { defaultPrevented: true }
  ])("输入、忙碌和系统组合键不触发审核：%j", (options) => {
    for (const key of ["x", " ", "ArrowRight", "s", "Delete"]) {
      const result = press(key, options);
      expect(result.handled).toBe(true);
      expect(result.onAction).not.toHaveBeenCalled();
    }
  });

  it("视频操作不作用于图片，输入中仍保留现有 Esc 关闭入口", () => {
    for (const key of ["j", "l", ",", ".", "s", "m", "f"]) {
      expect(press(key, { isVideo: false }).onAction).not.toHaveBeenCalled();
    }
    expect(press("Escape", { editing: true }).handled).toBe(false);
  });

  it("图片说明不包含视频操作，截图权限控制 S 的显示，业务操作没有重复键位", () => {
    expect(getAcquisitionReviewShortcuts(false, false).map((item) => item.key)).toEqual(["x", "ArrowLeft", "ArrowRight"]);
    expect(getAcquisitionReviewShortcuts(true, false).some((item) => item.action === "capture")).toBe(false);
    const full = getAcquisitionReviewShortcuts(true, true);
    expect(full.some((item) => item.key === "s")).toBe(true);
    expect(new Set(full.map((item) => item.action)).size).toBe(full.length);
  });
});
