import { useEffect, type ReactNode } from "react";

import { isTextEditingTarget } from "./utils";

type PhotoLightboxProps = {
  children: ReactNode;
  meta?: ReactNode;
  shellClassName?: string;
  busy?: boolean;
  keyboardEnabled?: boolean;
  canGoPrevious: boolean;
  canGoNext: boolean;
  previousLabel?: string;
  nextLabel?: string;
  onClose: () => void;
  onPrevious: () => void | Promise<void>;
  onNext: () => void | Promise<void>;
  onKeyDown?: (event: KeyboardEvent) => void;
};

export default function PhotoLightbox({
  children,
  meta,
  shellClassName = "",
  busy = false,
  keyboardEnabled = true,
  canGoPrevious,
  canGoNext,
  previousLabel,
  nextLabel,
  onClose,
  onPrevious,
  onNext,
  onKeyDown: onCustomKeyDown
}: PhotoLightboxProps) {
  useEffect(() => {
    if (!keyboardEnabled) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (busy || isTextEditingTarget(event.target)) return;
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "ArrowLeft" && canGoPrevious) {
        void onPrevious();
      } else if (event.key === "ArrowRight" && canGoNext) {
        void onNext();
      } else {
        onCustomKeyDown?.(event);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, canGoNext, canGoPrevious, keyboardEnabled, onClose, onCustomKeyDown, onNext, onPrevious]);

  return (
    <div className="lightbox-backdrop" onClick={onClose} role="presentation">
      <div
        className={`lightbox-shell ${shellClassName}`.trim()}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="图片大图预览"
      >
        <button className="lightbox-close" onClick={onClose}>关闭</button>
        <button
          className="lightbox-arrow left"
          disabled={!canGoPrevious || busy}
          onClick={() => void onPrevious()}
          aria-label={previousLabel || "上一张"}
        >
          ‹ {previousLabel && <span>{previousLabel}</span>}
        </button>
        {children}
        <button
          className="lightbox-arrow right"
          disabled={!canGoNext || busy}
          onClick={() => void onNext()}
          aria-label={nextLabel || "下一张"}
        >
          {nextLabel && <span>{nextLabel}</span>} ›
        </button>
      </div>
      {meta && (
        <aside className="lightbox-meta-rail" onClick={(event) => event.stopPropagation()}>
          {meta}
        </aside>
      )}
    </div>
  );
}
