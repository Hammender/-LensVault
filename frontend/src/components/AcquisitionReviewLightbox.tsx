import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode, type PointerEvent } from "react";
import { Camera, Check, ChevronDown, ChevronLeft, ChevronRight, ChevronUp, Film, Maximize2, Minimize2, Pause, Play, RotateCcw, Trash2, ZoomIn, ZoomOut, Volume1, Volume2, VolumeX } from "lucide-react";

import { acquisitionDownloadUrl } from "../api/acquisition";
import { formatVideoTime, parseVideoTime } from "../lib/acquisitionVideo";
import { useAcquisitionFrames } from "../lib/useAcquisitionFrames";
import { handleAcquisitionLightboxShortcut } from "../lib/acquisitionReview";
import { releaseHtmlVideo } from "../lib/htmlVideo";
import PhotoLightbox from "./PhotoLightbox";
import type { AcquisitionAsset, AcquisitionCaptureResult } from "../types";
import { formatBytes, formatDate, formatDurationSeconds } from "../lib/utils";
import "./AcquisitionReviewLightbox.css";

type AcquisitionReviewLightboxProps = {
  asset: AcquisitionAsset;
  statusLabel: string;
  indexLabel: string;
  selected: boolean;
  canDelete: boolean;
  canCapture?: boolean;
  onCaptured?: (result: AcquisitionCaptureResult) => void;
  onViewCapture?: (asset: AcquisitionAsset) => void;
  busy: boolean;
  canGoPrevious: boolean;
  canGoNext: boolean;
  extraMeta?: ReactNode;
  onClose: () => void;
  onPrevious: () => void | Promise<void>;
  onNext: () => void | Promise<void>;
  onToggleSelect: () => void;
  onReject: () => void;
};

export default function AcquisitionReviewLightbox({
  asset,
  statusLabel,
  indexLabel,
  selected,
  canDelete,
  canCapture = false,
  onCaptured,
  onViewCapture,
  busy,
  canGoPrevious,
  canGoNext,
  extraMeta,
  onClose,
  onPrevious,
  onNext,
  onToggleSelect,
  onReject
}: AcquisitionReviewLightboxProps) {
  const isVideo = asset.media_type === "video";
  const hasSource = Boolean(
    asset.source_caption
    || asset.source_hashtags.length
    || asset.source_message_url
    || asset.source_channel_title
    || asset.source_published_at
  );
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const playerRef = useRef<HTMLDivElement | null>(null);
  const { decoded, locating, saving, error: frameError, capture, clearFrame, prepareFrame, saveFrame } = useAcquisitionFrames(asset, videoRef, onCaptured);
  const [mediaReady, setMediaReady] = useState(false);
  const [buffering, setBuffering] = useState(true);
  const [mediaError, setMediaError] = useState<string | null>(null);
  const [bufferedTime, setBufferedTime] = useState(0);
  const [seeking, setSeeking] = useState(false);
  const [timeInput, setTimeInput] = useState("");
  const [timeError, setTimeError] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const dragRef = useRef<{ x: number; y: number; panX: number; panY: number } | null>(null);
  const [draggingProgress, setDraggingProgress] = useState(false);
  const resumeAfterSeek = useRef(false);
  const captionRef = useRef<HTMLParagraphElement | null>(null);
  const [captionExpanded, setCaptionExpanded] = useState(false);
  const [captionOverflows, setCaptionOverflows] = useState(false);
  const [isPlaying, setIsPlaying] = useState(true);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(0.15);
  const [duration, setDuration] = useState(asset.duration_seconds ?? 0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [showControls, setShowControls] = useState(true);
  const [indicatorText, setIndicatorText] = useState<string | null>(null);
  const indicatorTimerRef = useRef<number | null>(null);
  const hideControlsTimerRef = useRef<number | null>(null);

  const showIndicator = useCallback((text: string) => {
    setIndicatorText(text);
    if (indicatorTimerRef.current) window.clearTimeout(indicatorTimerRef.current);
    indicatorTimerRef.current = window.setTimeout(() => setIndicatorText(null), 1200);
  }, []);

  const revealControls = useCallback(() => {
    setShowControls(true);
    if (hideControlsTimerRef.current) window.clearTimeout(hideControlsTimerRef.current);
    hideControlsTimerRef.current = window.setTimeout(() => {
      if (videoRef.current && !videoRef.current.paused) setShowControls(false);
    }, 1800);
  }, []);

  useEffect(() => {
    setMediaReady(false);
    setBuffering(true);
    setMediaError(null);
    setBufferedTime(0);
    setSeeking(false);
    setTimeInput("");
    setTimeError(null);
    setZoom(1);
    setPan({ x: 0, y: 0 });
    setCurrentTime(0);
    setDuration(asset.duration_seconds ?? 0);
    setIsPlaying(true);
    setShowSpeedMenu(false);
    setCaptionExpanded(false);
  }, [asset.id, asset.duration_seconds]);

  useLayoutEffect(() => {
    const node = captionRef.current;
    if (!node) {
      setCaptionOverflows(false);
      return undefined;
    }
    const measure = () => {
      if (node.classList.contains("is-expanded")) return;
      setCaptionOverflows(node.scrollHeight > node.clientHeight + 1);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [asset.id, asset.source_caption]);

  useEffect(() => {
    const video = videoRef.current;
    if (!isVideo || !video) return undefined;
    let cancelled = false;
    let started = false;
    const tryPlay = () => {
      if (cancelled || started) return;
      started = true;
      video.playbackRate = playbackRate;
      video.volume = volume;
      video.muted = isMuted;
      void video.play().then(() => {
        if (!cancelled) setIsPlaying(true);
      }).catch(() => {
        if (!cancelled) setIsPlaying(false);
      });
    };
    video.addEventListener("loadeddata", tryPlay);
    // StrictMode 会先执行一次资源清理，再重跑 effect；恢复被清理的 src。
    if (asset.original_url && !video.getAttribute("src")) {
      video.src = acquisitionDownloadUrl(asset.original_url);
      video.load();
    }
    if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) tryPlay();
    return () => {
      cancelled = true;
      video.removeEventListener("loadeddata", tryPlay);
      if (document.fullscreenElement) void document.exitFullscreen().catch(() => {});
      releaseHtmlVideo(video);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [asset.id, isVideo]);

  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.volume = volume;
      videoRef.current.muted = isMuted;
    }
  }, [volume, isMuted]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = playbackRate;
  }, [playbackRate]);

  useEffect(() => {
    const onFullscreenChange = () => setIsFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", onFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", onFullscreenChange);
  }, []);

  useEffect(() => () => {
    if (indicatorTimerRef.current) window.clearTimeout(indicatorTimerRef.current);
    if (hideControlsTimerRef.current) window.clearTimeout(hideControlsTimerRef.current);
  }, []);

  const togglePlay = useCallback(() => {
    if (!videoRef.current || !mediaReady || locating || saving) return;
    if (videoRef.current.paused) {
      if (decoded) {
        videoRef.current.currentTime = decoded.frame.time_seconds;
        clearFrame();
        setZoom(1);
        setPan({ x: 0, y: 0 });
      }
      videoRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
      showIndicator("播放");
    } else {
      videoRef.current.pause();
      setIsPlaying(false);
      showIndicator("暂停");
    }
  }, [showIndicator, mediaReady, locating, saving, decoded, clearFrame]);

  const handleReject = useCallback(() => {
    if (saving) return;
    videoRef.current?.pause();
    setIsPlaying(false);
    onReject();
  }, [onReject, saving]);

  const toggleMute = useCallback(() => {
    if (!videoRef.current) return;
    if (isMuted || volume === 0) {
      const restoreVol = volume > 0 ? volume : 0.15;
      videoRef.current.muted = false;
      videoRef.current.volume = restoreVol;
      setIsMuted(false);
      setVolume(restoreVol);
      showIndicator(`音量: ${Math.round(restoreVol * 100)}%`);
    } else {
      videoRef.current.muted = true;
      setIsMuted(true);
      showIndicator("静音");
    }
  }, [isMuted, volume, showIndicator]);

  const seekTo = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video || !mediaReady || locating || saving || !Number.isFinite(duration) || duration <= 0) return;
    clearFrame();
    setZoom(1);
    setPan({ x: 0, y: 0 });
    video.currentTime = Math.max(0, Math.min(duration, seconds));
    setCurrentTime(video.currentTime);
  }, [mediaReady, locating, saving, duration, clearFrame]);

  const handleSeek = useCallback((delta: number) => {
    seekTo((decoded?.frame.time_seconds ?? videoRef.current?.currentTime ?? 0) + delta);
    showIndicator(`${delta > 0 ? "+" : ""}${delta}秒`);
  }, [seekTo, decoded, showIndicator]);

  const stepFrame = useCallback((direction: -1 | 0 | 1) => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    void prepareFrame(direction);
  }, [prepareFrame]);

  const toggleFullscreen = useCallback(() => {
    const node = playerRef.current;
    if (!node) return;
    const operation = document.fullscreenElement ? document.exitFullscreen() : node.requestFullscreen();
    void operation.catch(() => showIndicator("全屏不可用"));
  }, [showIndicator]);

  const displayedTime = decoded?.frame.time_seconds ?? currentTime;
  const captureDisabled = !canCapture || !mediaReady || seeking || locating || saving || busy || Boolean(mediaError);
  const frameDisabled = !mediaReady || seeking || locating || saving || busy || Boolean(mediaError);
  const seekFromPointer = (event: PointerEvent<HTMLInputElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    seekTo(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * duration);
  };

  const progressRatio = duration > 0 ? Math.min(1, displayedTime / duration) : 0;
  const media = isVideo && asset.original_url ? (
    <div
      ref={playerRef}
      className={`acquisition-review-player${showControls || !isPlaying ? " show-controls" : ""}`}
      onClick={togglePlay}
      onMouseMove={revealControls}
      onMouseLeave={() => {
        if (isPlaying) setShowControls(false);
      }}
    >
      <video
        key={asset.id}
        ref={videoRef}
        src={acquisitionDownloadUrl(asset.original_url)}
        poster={asset.preview_url ?? undefined}
        onLoadedData={() => { setMediaReady(true); setBuffering(false); }}
        onWaiting={() => setBuffering(true)}
        onCanPlay={() => setBuffering(false)}
        onError={() => { setMediaError("视频播放失败，请重试；若仍无法播放，请检查视频格式。"); setBuffering(false); setMediaReady(false); }}
        onSeeking={() => setSeeking(true)}
        onSeeked={() => setSeeking(false)}
        onProgress={() => {
          const video = videoRef.current;
          if (video?.buffered.length) setBufferedTime(video.buffered.end(video.buffered.length - 1));
        }}
        playsInline
        onTimeUpdate={() => {
          if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
        }}
        onLoadedMetadata={() => {
          if (videoRef.current) setDuration(Number.isFinite(videoRef.current.duration) ? videoRef.current.duration : 0);
        }}
        onPlay={() => {
          setIsPlaying(true);
          revealControls();
        }}
        onPause={() => {
          setIsPlaying(false);
          setShowControls(true);
        }}
        onEnded={() => {
          setIsPlaying(false);
          setShowControls(true);
        }}
      />
      <span className="acquisition-review-type-chip">视频</span>
      {decoded && <div
        className={`acquisition-review-frame-view${zoom > 1 ? " is-zoomed" : ""}`}
        onClick={(event) => event.stopPropagation()}
        onPointerDown={(event) => {
          if (zoom <= 1) return;
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
        <img src={decoded.url} alt={`第 ${decoded.frame.frame_index + 1} 帧`} style={{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})` }} draggable={false} />
      </div>}
      {(mediaError || (buffering && !decoded) || locating) && <div className="acquisition-review-player-status" onClick={(event) => event.stopPropagation()}>
        <span>{mediaError || (locating ? "正在准备精确画面…" : "正在加载视频…")}</span>
        {mediaError && <button type="button" onClick={() => {
          setMediaError(null); setBuffering(true); videoRef.current?.load();
          void videoRef.current?.play().catch(() => {});
        }}>重试播放</button>}
      </div>}
      <div className="acquisition-review-player-badges">
        {!isPlaying && mediaReady && <span>{decoded ? `精细选帧 · 第 ${decoded.frame.frame_index + 1} 帧` : "已暂停"}</span>}
        {indicatorText && <span>{indicatorText}</span>}
      </div>
      <div className="acquisition-review-controls" onClick={(event) => event.stopPropagation()}>
        <div className="acquisition-review-progress-wrap">
          <div className="acquisition-review-progress-buffer" style={{ width: `${duration > 0 ? Math.min(100, bufferedTime / duration * 100) : 0}%` }} />
          <input
            className="acquisition-review-progress-range"
            type="range" min={0} max={duration || 1} step={0.001} value={displayedTime}
            aria-label="视频播放进度" aria-valuetext={formatVideoTime(displayedTime, true)}
            title={formatVideoTime(displayedTime, true)}
            disabled={!mediaReady || locating || saving || busy || Boolean(mediaError) || duration <= 0}
            style={{ background: `linear-gradient(to right, #9fe0d8 ${progressRatio * 100}%, transparent ${progressRatio * 100}%)` }}
            onPointerDown={(event) => {
              if (frameDisabled) return;
              resumeAfterSeek.current = Boolean(videoRef.current && !videoRef.current.paused);
              videoRef.current?.pause();
              event.currentTarget.setPointerCapture(event.pointerId);
              setDraggingProgress(true);
              seekFromPointer(event);
            }}
            onPointerMove={(event) => { if (draggingProgress) seekFromPointer(event); }}
            onPointerUp={() => {
              setDraggingProgress(false);
              if (resumeAfterSeek.current) void videoRef.current?.play().catch(() => {});
              resumeAfterSeek.current = false;
            }}
            onPointerCancel={() => { setDraggingProgress(false); resumeAfterSeek.current = false; }}
            onChange={(event) => seekTo(Number(event.target.value))}
          />
        </div>
        <div className="acquisition-review-ctrl-row">
          <div className="acquisition-review-ctrl-left">
            <button type="button" className="acquisition-review-ctrl-btn" onClick={togglePlay} title="播放/暂停（空格）" aria-label={isPlaying ? "暂停" : "播放"} disabled={!mediaReady || locating || saving}>
              {isPlaying ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <div className="acquisition-review-volume">
              <button type="button" className="acquisition-review-ctrl-btn" onClick={toggleMute} title="静音（M）" aria-label={isMuted ? "取消静音" : "静音"}>
                {isMuted || volume === 0 ? <VolumeX size={18} /> : volume < 0.5 ? <Volume1 size={18} /> : <Volume2 size={18} />}
              </button>
              <div className="acquisition-review-volume-slider">
                <input
                  aria-label="视频音量"
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={isMuted ? 0 : volume}
                  style={{
                    background: `linear-gradient(to right, #9fe0d8 ${(isMuted ? 0 : volume) * 100}%, rgba(255, 255, 255, 0.28) ${(isMuted ? 0 : volume) * 100}%)`
                  }}
                  onChange={(event) => {
                    const next = Number(event.target.value);
                    setVolume(next);
                    setIsMuted(next === 0);
                    if (videoRef.current) {
                      videoRef.current.volume = next;
                      videoRef.current.muted = next === 0;
                    }
                  }}
                />
              </div>
            </div>
            <span className="acquisition-review-time">{formatVideoTime(displayedTime, true)} / {formatVideoTime(duration)}</span>
          </div>
          <div className={`acquisition-review-frame-step${decoded ? " is-active" : ""}`} role="group" aria-label="逐帧选画面" aria-busy={locating}>
            <button type="button" className="acquisition-review-frame-step-btn" disabled={frameDisabled || decoded?.frame.frame_index === 0} onClick={() => stepFrame(-1)} title="上一帧（逗号）" aria-label="上一帧"><ChevronLeft size={17} /></button>
            <span className="acquisition-review-frame-step-label"><Film size={14} aria-hidden="true" />逐帧</span>
            <button type="button" className="acquisition-review-frame-step-btn" disabled={frameDisabled || (decoded ? decoded.frame.frame_index === decoded.frame.total_frames - 1 : false)} onClick={() => stepFrame(1)} title="下一帧（句号）" aria-label="下一帧"><ChevronRight size={17} /></button>
          </div>
          <div className="acquisition-review-ctrl-right">
            <button type="button" className="acquisition-review-ctrl-btn" disabled={frameDisabled} onClick={() => handleSeek(-5)} title="快退 5 秒（J）" aria-label="快退 5 秒"><RotateCcw size={17} /></button>
            <button type="button" className="acquisition-review-ctrl-btn" disabled={frameDisabled} onClick={() => handleSeek(5)} title="快进 5 秒（L）" aria-label="快进 5 秒"><RotateCcw size={17} style={{ transform: "scaleX(-1)" }} /></button>
            {canCapture && <button type="button" className="acquisition-review-ctrl-btn capture-btn" disabled={captureDisabled} onClick={() => void saveFrame()} title="截取当前帧（S）" aria-label="截取当前帧"><Camera size={18} /></button>}

            <div className="acquisition-review-speed">
              <button
                type="button"
                className={`acquisition-review-ctrl-btn speed-btn${showSpeedMenu ? " active" : ""}`}
                onClick={() => setShowSpeedMenu((current) => !current)}
                title="倍速" aria-label="播放倍速" aria-expanded={showSpeedMenu}
              >
                {playbackRate}x
              </button>
              {showSpeedMenu && (
                <div className="acquisition-review-speed-menu">
                  {[2, 1.5, 1.25, 1, 0.75, 0.5].map((rate) => (
                    <button
                      key={rate}
                      type="button"
                      className={playbackRate === rate ? "active" : ""}
                      onClick={() => {
                        setPlaybackRate(rate);
                        if (videoRef.current) videoRef.current.playbackRate = rate;
                        setShowSpeedMenu(false);
                        showIndicator(`${rate}x`);
                      }}
                    >
                      {rate}x
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button type="button" className="acquisition-review-ctrl-btn" onClick={toggleFullscreen} title="全屏（F）" aria-label={isFullscreen ? "退出全屏" : "进入全屏"}>
              {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>
        </div>
      </div>
      {decoded && <div className="acquisition-review-zoom-tools" onClick={(event) => event.stopPropagation()}>
        <button type="button" onClick={() => { setZoom(1); setPan({ x: 0, y: 0 }); }} title="适应窗口">适应</button>
        <button type="button" onClick={() => {
          const image = playerRef.current?.querySelector<HTMLImageElement>(".acquisition-review-frame-view img");
          if (image) { setZoom(image.naturalWidth / image.clientWidth); setPan({ x: 0, y: 0 }); }
        }} title="按图片原始像素查看">原尺寸</button>
        <button type="button" onClick={() => setZoom((value) => Math.max(1, value / 1.5))} aria-label="缩小画面"><ZoomOut size={16} /></button>
        <span>{Math.round(zoom * 100)}%</span>
        <button type="button" onClick={() => setZoom((value) => Math.min(12, value * 1.5))} aria-label="放大画面"><ZoomIn size={16} /></button>
      </div>}
      {isFullscreen && (frameError || saving || capture) && <div className="acquisition-review-fullscreen-notice" role="status">
        {frameError || (saving ? "正在保存原尺寸截图…" : capture?.outcome === "imported" ? "该画面已在图库中" : "截图已保存到待审核区")}
      </div>}
    </div>
  ) : !asset.original_url ? (
    <div className="tile-missing">临时文件已清除</div>
  ) : null;

  return (
    <PhotoLightbox
      image={!isVideo && asset.original_url ? { src: asset.original_url, alt: asset.filename } : undefined}
      backdropClassName="acquisition-review-lightbox-backdrop"
      shellClassName={`acquisition-review-lightbox${isVideo ? " is-video" : ""}`}
      ariaLabel={isVideo ? "采集视频预览" : "采集图片预览"}
      busy={busy}
      ignoreInteractiveTargets
      canGoPrevious={canGoPrevious}
      canGoNext={canGoNext}
      onClose={() => {
        if (isVideo && document.fullscreenElement) { void document.exitFullscreen().catch(() => {}); return; }
        onClose();
      }}
      previousLabel="上一项"
      nextLabel="下一项"
      onPrevious={onPrevious}
      onNext={onNext}
      onKeyDown={(event) => {
        if (event.target instanceof Element && event.target.closest("button, input, select, textarea, a, [contenteditable]")) return;
        if (event.ctrlKey || event.metaKey || event.altKey) return;
        if (isVideo) {
          if (event.key === "," || event.key === ".") {
            event.preventDefault();
            if (!frameDisabled && !event.repeat) stepFrame(event.key === "," ? -1 : 1);
            return;
          }
          if (event.key.toLowerCase() === "s") {
            event.preventDefault();
            if (!captureDisabled && !event.repeat) void saveFrame();
            return;
          }
          if (event.key === " ") {
            event.preventDefault();
            if (!event.repeat) togglePlay();
            return;
          }
          if (event.key === "j" || event.key === "J" || (event.key === "ArrowLeft" && event.shiftKey)) {
            event.preventDefault();
            handleSeek(-5);
            return;
          }
          if (event.key === "l" || event.key === "L" || (event.key === "ArrowRight" && event.shiftKey)) {
            event.preventDefault();
            handleSeek(5);
            return;
          }
          if (event.key === "m" || event.key === "M") {
            event.preventDefault();
            toggleMute();
            return;
          }
          if (event.key === "f" || event.key === "F") {
            event.preventDefault();
            toggleFullscreen();
            return;
          }
        }
        handleAcquisitionLightboxShortcut(event, asset.media_type, {
          onToggleSelect,
          onReject: canDelete ? handleReject : undefined
        });
      }}
      meta={
        <>
          <div className="acquisition-lightbox-heading">
            <div>
              <p className="acquisition-eyebrow">采集审核</p>
              <h2>{statusLabel}</h2>
            </div>
            <div className="acquisition-lightbox-heading-tools">
              <strong>{indexLabel}</strong>
              <button type="button" className="acquisition-lightbox-close" onClick={onClose}>关闭</button>
            </div>
          </div>
          {isVideo && <section className="acquisition-review-capture-panel">
            <div className="acquisition-review-capture-heading"><Camera size={19} /><strong>视频截图</strong><span>原尺寸 PNG</span></div>
            <p>暂停后选好画面，截图将加入待审核区。首次处理该视频需读取原片，长视频可能稍久。</p>
            {canCapture && <button className="acquisition-review-capture-command" type="button" disabled={captureDisabled} onClick={() => void saveFrame()}>
              <Camera size={18} />{saving ? "正在保存截图…" : "截取当前帧"}
            </button>}
            <form className="acquisition-review-time-form" onSubmit={(event) => {
              event.preventDefault();
              const seconds = parseVideoTime(timeInput);
              if (seconds === null || seconds > duration) { setTimeError("请输入视频时长范围内的时间，如 01:23.456"); return; }
              setTimeError(null);
              void prepareFrame(0, seconds);
            }}>
              <input aria-label="精确定位时间" placeholder={formatVideoTime(displayedTime, true)} value={timeInput} onChange={(event) => setTimeInput(event.target.value)} disabled={frameDisabled} />
              <button type="submit" disabled={frameDisabled}>定位</button>
            </form>
            {!decoded && <button className="acquisition-review-prepare-command" type="button" disabled={frameDisabled} onClick={() => stepFrame(0)}>进入精细选帧</button>}
            {(timeError || frameError) && <p className="acquisition-review-capture-error" role="alert">{timeError || frameError}</p>}
            <div role="status" aria-live="polite">
              {locating && <p>正在准备精确画面，首次读取可能稍久…</p>}
              {capture && <div className="acquisition-review-capture-result">
                {capture.asset.preview_url && <img src={acquisitionDownloadUrl(capture.asset.preview_url)} alt="刚保存的视频截图" />}
                <div><strong>{capture.outcome === "imported" ? "该画面已在图库中" : capture.outcome === "existing" ? "该截图已在审核列表中" : "已添加到待审核·图片"}</strong>
                  {capture.asset.status === "pending_review" && <button type="button" onClick={() => onViewCapture?.(capture.asset)}>查看截图</button>}
                </div>
              </div>}
            </div>
          </section>}
          {asset.capture_metadata && <section className="acquisition-review-capture-origin">
            <strong>视频截图来源</strong>
            <p>{asset.capture_metadata.video_filename}</p>
            <small>截帧时间 {formatVideoTime(asset.capture_metadata.time_seconds, true)} · 第 {asset.capture_metadata.frame_index + 1} 帧</small>
          </section>}
          {extraMeta}
          <dl className="acquisition-lightbox-facts">
            <div className="span-all"><dt>文件名</dt><dd title={asset.filename}>{asset.filename}</dd></div>
            <div>
              <dt>{isVideo ? "画面" : "尺寸"}</dt>
              <dd>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "未知"}</dd>
            </div>
            <div><dt>大小</dt><dd>{formatBytes(asset.size_bytes)}</dd></div>
            {isVideo && (
              <div className="span-all">
                <dt>时长</dt>
                <dd>{asset.duration_seconds != null ? formatDurationSeconds(asset.duration_seconds) : "未知"}</dd>
              </div>
            )}
          </dl>
          <section className={asset.quality_warnings.length ? "acquisition-quality-notes has-warning" : "acquisition-quality-notes"}>
            <strong>质量提示</strong>
            <p title={asset.quality_warnings.length ? asset.quality_warnings.join(" / ") : undefined}>
              {asset.quality_warnings.length ? asset.quality_warnings.join(" / ") : "未发现自动质量提示"}
            </p>
          </section>
          <div className="acquisition-lightbox-actions">
            <button type="button" className={selected ? "selected" : ""} onClick={onToggleSelect} disabled={busy}>
              <Check size={17} /> {selected ? "取消选择" : "选中当前"}
            </button>
            {canDelete && (
              <button type="button" className="danger-command" onClick={handleReject} disabled={busy || saving}>
                <Trash2 size={17} /> 丢弃当前
              </button>
            )}
          </div>
          {hasSource && (
            <section className="acquisition-review-copy">
              <h3>来源文案</h3>
              <p
                ref={captionRef}
                className={`acquisition-review-copy-body${captionExpanded ? " is-expanded" : ""}`}
              >
                {asset.source_caption || "这条消息没有正文。"}
              </p>
              {(captionOverflows || captionExpanded) && (
                <button
                  type="button"
                  className="acquisition-review-copy-toggle"
                  aria-expanded={captionExpanded}
                  onClick={() => setCaptionExpanded((current) => !current)}
                >
                  {captionExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  {captionExpanded ? "收起" : "展开全文"}
                </button>
              )}
              {asset.source_hashtags.length > 0 && (
                <div className="micro-row wrap">
                  {asset.source_hashtags.map((tag) => (
                    <small key={tag} className="acquisition-hashtag">#{tag}</small>
                  ))}
                </div>
              )}
              <div className="micro-row wrap">
                {asset.source_channel_title && <span>{asset.source_channel_title}</span>}
                {asset.source_published_at && <span>{formatDate(asset.source_published_at)}</span>}
                {asset.source_message_url && (
                  <a href={asset.source_message_url} target="_blank" rel="noreferrer">打开原消息</a>
                )}
              </div>
            </section>
          )}
          {isVideo && (
            <section className="acquisition-review-shortcuts">
              <strong>快捷键</strong>
              <p>空格播放 · , / . 逐帧 · S 截图 · J / L 前后 5 秒 · Enter 选中 · M 静音 · F 全屏 · ← / → 切换素材</p>
            </section>
          )}
        </>
      }
    >
      {media}
    </PhotoLightbox>
  );
}
