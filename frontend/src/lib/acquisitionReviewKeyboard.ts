export type AcquisitionReviewAction =
  | "select" | "previous" | "next" | "play" | "seek_back" | "seek_forward"
  | "previous_frame" | "next_frame" | "capture" | "mute" | "fullscreen" | "reject";

type Shortcut = {
  key: string;
  label: string;
  description: string;
  action: AcquisitionReviewAction;
  videoOnly?: boolean;
  captureOnly?: boolean;
  repeat?: boolean;
};

export const acquisitionReviewShortcuts: readonly Shortcut[] = [
  { key: "x", label: "X", description: "选中 / 取消选中", action: "select" },
  { key: "ArrowLeft", label: "←", description: "上一项素材", action: "previous" },
  { key: "ArrowRight", label: "→", description: "下一项素材", action: "next" },
  { key: " ", label: "空格", description: "播放 / 暂停", action: "play", videoOnly: true },
  { key: "j", label: "J", description: "后退 2 秒", action: "seek_back", videoOnly: true, repeat: true },
  { key: "l", label: "L", description: "前进 2 秒", action: "seek_forward", videoOnly: true, repeat: true },
  { key: ",", label: ",", description: "上一帧", action: "previous_frame", videoOnly: true },
  { key: ".", label: ".", description: "下一帧", action: "next_frame", videoOnly: true },
  { key: "s", label: "S", description: "截取当前帧", action: "capture", videoOnly: true, captureOnly: true },
  { key: "m", label: "M", description: "静音 / 取消静音", action: "mute", videoOnly: true },
  { key: "f", label: "F", description: "进入 / 退出全屏", action: "fullscreen", videoOnly: true }
];

export function getAcquisitionReviewShortcuts(isVideo: boolean, canCapture: boolean) {
  return acquisitionReviewShortcuts.filter((shortcut) =>
    (!shortcut.videoOnly || isVideo) && (!shortcut.captureOnly || canCapture));
}

type ShortcutEvent = Pick<KeyboardEvent,
  "key" | "repeat" | "defaultPrevented" | "ctrlKey" | "metaKey" | "altKey" | "shiftKey" | "isComposing" | "preventDefault">;

export function handleAcquisitionReviewKeyDown(
  event: ShortcutEvent,
  context: {
    isVideo: boolean;
    editing: boolean;
    range: boolean;
    blocked: boolean;
    onAction: (action: AcquisitionReviewAction) => void;
  }
): boolean {
  // 返回 true 也可只保留原生行为，避免再落入共享灯箱的默认按键处理。
  if (event.defaultPrevented || event.isComposing || event.ctrlKey || event.metaKey || event.altKey) return true;
  if (context.editing && event.key !== "Escape") return true;
  if ((event.key === "ArrowLeft" || event.key === "ArrowRight") && (event.shiftKey || context.range)) return true;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  const shortcut = acquisitionReviewShortcuts.find((item) => item.key === key && (!item.videoOnly || context.isVideo));
  const action = shortcut?.action ?? (key === "Delete" ? "reject" : null);
  if (!action) return false;
  event.preventDefault();
  if (!context.blocked && (!event.repeat || shortcut?.repeat)) context.onAction(action);
  return true;
}
