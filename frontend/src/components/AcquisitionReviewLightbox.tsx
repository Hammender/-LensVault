import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Check, Maximize2, Minimize2, Pause, Play, Trash2, Volume1, Volume2, VolumeX } from "lucide-react";

import { acquisitionDownloadUrl } from "../api/acquisition";
import { getAcquisitionLightboxShortcut } from "../lib/acquisitionReview";
import PhotoLightbox from "./PhotoLightbox";
import type { AcquisitionAsset } from "../types";
import { formatBytes, formatDate, formatDurationSeconds } from "../lib/utils";
import "./AcquisitionReviewLightbox.css";

function formatClock(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

type AcquisitionReviewLightboxProps = {
  asset: AcquisitionAsset;
  statusLabel: string;
  indexLabel: string;
  selected: boolean;
  canDelete: boolean;
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
  const hasCaption = Boolean(asset.source_caption || asset.source_hashtags.length || asset.source_message_url);
  const videoRef = useRef<HTMLVideoElement | null>(null);
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
    setCurrentTime(0);
    setDuration(asset.duration_seconds ?? 0);
    setIsPlaying(true);
    setShowSpeedMenu(false);
  }, [asset.id, asset.duration_seconds]);

  useEffect(() => {
    if (!isVideo || !videoRef.current) return;
    videoRef.current.currentTime = 0;
    videoRef.current.playbackRate = playbackRate;
    videoRef.current.volume = volume;
    videoRef.current.muted = isMuted;
    videoRef.current.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
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
    if (!videoRef.current) return;
    if (videoRef.current.paused) {
      videoRef.current.play().then(() => setIsPlaying(true)).catch(() => {});
      showIndicator("播放");
    } else {
      videoRef.current.pause();
      setIsPlaying(false);
      showIndicator("暂停");
    }
  }, [showIndicator]);

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

  const handleSeek = useCallback((delta: number) => {
    if (!videoRef.current) return;
    const next = Math.max(0, Math.min(videoRef.current.duration || 0, videoRef.current.currentTime + delta));
    videoRef.current.currentTime = next;
    setCurrentTime(next);
    showIndicator(`${delta > 0 ? "+" : ""}${delta}秒`);
  }, [showIndicator]);

  const toggleFullscreen = useCallback(() => {
    const node = videoRef.current?.parentElement;
    if (!node) return;
    if (!document.fullscreenElement) {
      node.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  }, []);

  const progressRatio = duration > 0 ? Math.min(1, currentTime / duration) : 0;
  const media = isVideo && asset.original_url ? (
    <div
      className={`acquisition-review-player${showControls || !isPlaying ? " show-controls" : ""}`}
      onClick={togglePlay}
      onMouseMove={revealControls}
      onMouseLeave={() => {
        if (isPlaying) setShowControls(false);
      }}
    >
      <video
        ref={videoRef}
        src={acquisitionDownloadUrl(asset.original_url)}
        poster={asset.preview_url ?? undefined}
        playsInline
        onTimeUpdate={() => {
          if (videoRef.current) setCurrentTime(videoRef.current.currentTime);
        }}
        onLoadedMetadata={() => {
          if (videoRef.current) setDuration(videoRef.current.duration);
        }}
        onPlay={() => {
          setIsPlaying(true);
          revealControls();
        }}
        onPause={() => {
          setIsPlaying(false);
          setShowControls(true);
        }}
      />
      <span className="acquisition-review-type-chip">视频</span>
      {!isPlaying && (
        <div className="acquisition-review-pause-overlay">
          <div className="acquisition-review-pause-icon"><Play size={30} fill="currentColor" /></div>
        </div>
      )}
      {indicatorText && <div className="acquisition-review-indicator">{indicatorText}</div>}
      <div className="acquisition-review-controls" onClick={(event) => event.stopPropagation()}>
        <div
          className="acquisition-review-progress"
          onClick={(event) => {
            const rect = event.currentTarget.getBoundingClientRect();
            const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
            if (videoRef.current && duration > 0) {
              const nextTime = ratio * duration;
              videoRef.current.currentTime = nextTime;
              setCurrentTime(nextTime);
            }
          }}
        >
          <div className="acquisition-review-progress-fill" style={{ width: `${progressRatio * 100}%` }} />
        </div>
        <div className="acquisition-review-ctrl-row">
          <div className="acquisition-review-ctrl-left">
            <button type="button" className="acquisition-review-ctrl-btn" onClick={togglePlay} title="播放/暂停">
              {isPlaying ? <Pause size={18} /> : <Play size={18} />}
            </button>
            <div className="acquisition-review-volume">
              <button type="button" className="acquisition-review-ctrl-btn" onClick={toggleMute} title="静音">
                {isMuted || volume === 0 ? <VolumeX size={18} /> : volume < 0.5 ? <Volume1 size={18} /> : <Volume2 size={18} />}
              </button>
              <div className="acquisition-review-volume-slider">
                <input
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
            <span className="acquisition-review-time">{formatClock(currentTime)} / {formatClock(duration)}</span>
          </div>
          <div className="acquisition-review-ctrl-right">
            <div className="acquisition-review-speed">
              <button
                type="button"
                className={`acquisition-review-ctrl-btn speed-btn${showSpeedMenu ? " active" : ""}`}
                onClick={() => setShowSpeedMenu((current) => !current)}
                title="倍速"
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
            <button type="button" className="acquisition-review-ctrl-btn" onClick={toggleFullscreen} title="全屏">
              {isFullscreen ? <Minimize2 size={18} /> : <Maximize2 size={18} />}
            </button>
          </div>
        </div>
      </div>
    </div>
  ) : asset.original_url ? (
    <img className="lightbox-image" src={asset.original_url} alt={asset.filename} />
  ) : (
    <div className="tile-missing">临时文件已清除</div>
  );

  const copy = hasCaption ? (
    <aside className="rich-lightbox-copy acquisition-review-copy">
      <h3>来源文案</h3>
      <p>{asset.source_caption || "这条消息没有正文。"}</p>
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
    </aside>
  ) : null;

  return (
    <PhotoLightbox
      backdropClassName="acquisition-review-lightbox-backdrop"
      shellClassName={`acquisition-review-lightbox${hasCaption ? " rich-lightbox" : ""}`}
      ariaLabel={isVideo ? "采集视频预览" : "采集图片预览"}
      busy={busy}
      canGoPrevious={canGoPrevious}
      canGoNext={canGoNext}
      previousLabel="上一项"
      nextLabel="下一项"
      onClose={onClose}
      onPrevious={onPrevious}
      onNext={onNext}
      onKeyDown={(event) => {
        if (isVideo) {
          if (event.key === " ") {
            event.preventDefault();
            togglePlay();
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
        const shortcut = getAcquisitionLightboxShortcut(event.key, asset.media_type);
        if (shortcut === "toggle_selection") {
          event.preventDefault();
          onToggleSelect();
        } else if (shortcut === "reject" && canDelete) {
          event.preventDefault();
          onReject();
        }
      }}
      meta={
        <>
          <div className="acquisition-lightbox-heading">
            <div>
              <p className="acquisition-eyebrow">采集审核</p>
              <h2>{statusLabel}</h2>
            </div>
            <strong>{indexLabel}</strong>
          </div>
          {extraMeta}
          <dl className="acquisition-lightbox-facts">
            <div><dt>文件名</dt><dd title={asset.filename}>{asset.filename}</dd></div>
            <div>
              <dt>{isVideo ? "画面" : "尺寸"}</dt>
              <dd>{asset.width && asset.height ? `${asset.width} × ${asset.height}` : "未知"}</dd>
            </div>
            {isVideo && (
              <div>
                <dt>时长</dt>
                <dd>{asset.duration_seconds != null ? formatDurationSeconds(asset.duration_seconds) : "未知"}</dd>
              </div>
            )}
            <div><dt>大小</dt><dd>{formatBytes(asset.size_bytes)}</dd></div>
          </dl>
          <section className={asset.quality_warnings.length ? "acquisition-quality-notes has-warning" : "acquisition-quality-notes"}>
            <strong>质量提示</strong>
            <p>{asset.quality_warnings.length ? asset.quality_warnings.join(" / ") : "未发现自动质量提示"}</p>
          </section>
          {isVideo && (
            <section className="acquisition-review-shortcuts">
              <strong>快捷键</strong>
              <p>空格播放 · Enter 选中 · J / L 快退快进 · M 静音 · F 全屏</p>
            </section>
          )}
          <div className="acquisition-lightbox-actions">
            <button type="button" className={selected ? "selected" : ""} onClick={onToggleSelect} disabled={busy}>
              <Check size={17} /> {selected ? "取消选择" : "选中当前"}
            </button>
            {canDelete && (
              <button type="button" className="danger-command" onClick={onReject} disabled={busy}>
                <Trash2 size={17} /> 丢弃当前
              </button>
            )}
          </div>
        </>
      }
    >
      {hasCaption ? (
        <div className="rich-lightbox-layout">
          <div className="rich-lightbox-image-wrap">{media}</div>
          {copy}
        </div>
      ) : media}
    </PhotoLightbox>
  );
}
