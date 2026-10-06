import { useEffect, useRef, useState, type ReactNode } from "react";

import { isTextEditingTarget } from "../lib/utils";

type PhotoLightboxProps = {
  children?: ReactNode | ((image: ReactNode) => ReactNode);
  image?: { src: string; alt: string };
  meta?: ReactNode;
  backdropClassName?: string;
  shellClassName?: string;
  busy?: boolean;
  keyboardEnabled?: boolean;
  ignoreInteractiveTargets?: boolean;
  canGoPrevious: boolean;
  canGoNext: boolean;
  previousLabel?: string;
  nextLabel?: string;
  ariaLabel?: string;
  onClose: () => void;
  onPrevious: () => void | Promise<void>;
  onNext: () => void | Promise<void>;
  onKeyDown?: (event: KeyboardEvent) => void;
};

export default function PhotoLightbox({
  children,
  image,
  meta,
  backdropClassName = "",
  shellClassName = "",
  busy = false,
  keyboardEnabled = true,
  ignoreInteractiveTargets = false,
  canGoPrevious,
  canGoNext,
  previousLabel,
  nextLabel,
  ariaLabel = "图片大图预览",
  onClose,
  onPrevious,
  onNext,
  onKeyDown: onCustomKeyDown
}: PhotoLightboxProps) {
  const shellRef = useRef<HTMLDivElement>(null);
  const imageStageRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [mode, setMode] = useState<"fit" | "actual" | "manual">("fit");
  const [manualScale, setManualScale] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [imageSize, setImageSize] = useState<{ src: string; width: number; height: number } | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [stageSize, setStageSize] = useState({ width: 0, height: 0 });
  const [pixelRatio, setPixelRatio] = useState(window.devicePixelRatio || 1);
  const loadedImage = imageSize?.src === image?.src ? imageSize : null;
  const naturalWidth = loadedImage ? loadedImage.width / pixelRatio : 0;
  const naturalHeight = loadedImage ? loadedImage.height / pixelRatio : 0;
  const fitScale = naturalWidth && naturalHeight && stageSize.width && stageSize.height
    ? Math.min(stageSize.width / naturalWidth, stageSize.height / naturalHeight) : 1;
  const scale = mode === "fit" ? fitScale : mode === "actual" ? 1 : manualScale;

  useEffect(() => {
    setMode("fit");
    setManualScale(1);
    setPan({ x: 0, y: 0 });
    setImageFailed(false);
    dragRef.current = null;
  }, [image?.src]);

  useEffect(() => {
    const stage = imageStageRef.current;
    if (!stage) return undefined;
    const measure = () => {
      setStageSize({ width: stage.clientWidth, height: stage.clientHeight });
      setPixelRatio(window.devicePixelRatio || 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(stage);
    window.addEventListener("resize", measure);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, [image?.src]);

  const switchMode = () => {
    setMode((current) => current === "actual" ? "fit" : "actual");
    setPan({ x: 0, y: 0 });
  };
  const zoom = (factor: number) => {
    setManualScale(Math.max(0.1, Math.min(16, scale * factor)));
    setMode("manual");
  };

  useEffect(() => {
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    shellRef.current?.focus({ preventScroll: true });
    return () => {
      if (trigger?.isConnected) trigger.focus({ preventScroll: true });
    };
  }, []);

  useEffect(() => {
    if (!keyboardEnabled) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return;
      const lightboxes = document.querySelectorAll(".lightbox-backdrop");
      if (shellRef.current?.closest(".lightbox-backdrop") !== lightboxes[lightboxes.length - 1]) return;
      if (image && (event.key === "o" || event.key === "O") && !event.ctrlKey && !event.metaKey
          && !event.altKey && !isTextEditingTarget(event.target)) {
        event.preventDefault();
        if (!event.repeat) switchMode();
        return;
      }
      if (ignoreInteractiveTargets && event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (busy || isTextEditingTarget(event.target)) return;
      const onActivatingControl = ignoreInteractiveTargets
        && event.target instanceof Element
        && event.target.closest("button, a, [role=button]");
      if (onActivatingControl && (event.key === "Enter" || event.key === " ")) return;
      if (event.key === "Escape") {
        onClose();
      } else if (event.key === "ArrowLeft" && canGoPrevious && !event.shiftKey) {
        void onPrevious();
      } else if (event.key === "ArrowRight" && canGoNext && !event.shiftKey) {
        void onNext();
      } else {
        onCustomKeyDown?.(event);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, canGoNext, canGoPrevious, image, keyboardEnabled, ignoreInteractiveTargets, onClose, onCustomKeyDown, onNext, onPrevious]);

  const imageNode = image ? (
    <div
      ref={imageStageRef}
      className={`lightbox-image-stage${scale > fitScale ? " is-draggable" : ""}`}
      onPointerDown={(event) => {
        if (scale <= fitScale || event.button !== 0) return;
        event.currentTarget.setPointerCapture(event.pointerId);
        dragRef.current = { x: event.clientX, y: event.clientY, panX: pan.x, panY: pan.y };
      }}
      onPointerMove={(event) => {
        const drag = dragRef.current;
        if (drag) setPan({ x: drag.panX + event.clientX - drag.x, y: drag.panY + event.clientY - drag.y });
      }}
      onPointerUp={() => { dragRef.current = null; }}
      onPointerCancel={() => { dragRef.current = null; }}
    >
      {!loadedImage && !imageFailed && <span className="lightbox-image-message">正在加载原图…</span>}
      {imageFailed && <span className="lightbox-image-message" role="alert">原图加载失败，请重试</span>}
      <img
        key={image.src}
        src={image.src}
        alt={image.alt}
        draggable={false}
        style={loadedImage ? {
          width: naturalWidth,
          height: naturalHeight,
          transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${scale})`
        } : { visibility: "hidden" }}
        onLoad={(event) => {
          setImageSize({ src: image.src, width: event.currentTarget.naturalWidth, height: event.currentTarget.naturalHeight });
          setImageFailed(false);
        }}
        onError={() => { setImageSize(null); setImageFailed(true); }}
      />
    </div>
  ) : null;

  return (
    <div className={`lightbox-backdrop ${backdropClassName}`.trim()} onClick={onClose} role="presentation">
      <div
        ref={shellRef}
        className={`lightbox-shell ${shellClassName}`.trim()}
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        tabIndex={-1}
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
        {image ? typeof children === "function" ? children(imageNode) : imageNode : typeof children === "function" ? null : children}
        <button
          className="lightbox-arrow right"
          disabled={!canGoNext || busy}
          onClick={() => void onNext()}
          aria-label={nextLabel || "下一张"}
        >
          {nextLabel && <span>{nextLabel}</span>} ›
        </button>
      </div>
      {(meta || image) && (
        <aside className={`lightbox-meta-rail${image ? " has-image-controls" : ""}`} onClick={(event) => event.stopPropagation()}>
          {image ? <div className="lightbox-meta-content">{meta}</div> : meta}
          {image && <div className="lightbox-image-controls" role="group" aria-label="图片查看方式">
            <span>原图 {loadedImage ? `${loadedImage.width} × ${loadedImage.height}` : imageFailed ? "加载失败" : "加载中"}</span>
            <div className="lightbox-image-mode-buttons">
              <button type="button" aria-pressed={mode === "fit"} disabled={!loadedImage} onClick={() => { setMode("fit"); setPan({ x: 0, y: 0 }); }}>适应窗口</button>
              <button type="button" aria-pressed={mode === "actual"} disabled={!loadedImage} onClick={() => { setMode("actual"); setPan({ x: 0, y: 0 }); }}>原尺寸</button>
            </div>
            <div className="lightbox-image-zoom-buttons">
              <button type="button" aria-label="缩小图片" disabled={!loadedImage} onClick={() => zoom(0.8)}>−</button>
              <output aria-label="图片缩放比例">{loadedImage ? `${Math.round(scale * 100)}%` : "—"}</output>
              <button type="button" aria-label="放大图片" disabled={!loadedImage} onClick={() => zoom(1.25)}>＋</button>
            </div>
            <small>按 O 切换适应窗口与原尺寸</small>
          </div>}
        </aside>
      )}
    </div>
  );
}
