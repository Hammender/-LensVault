import React, { useCallback, useEffect, useRef, useState } from "react";
import {
  Edit3,
  ExternalLink,
  Film,
  Sparkles,
  Maximize2,
  Minimize2,
  Pause,
  Play,
  Subtitles,
  Volume1,
  Volume2,
  VolumeX,
  X
} from "lucide-react";

import type { VideoItem } from "./types";
import { formatDate, formatDurationSeconds, formatBytes } from "./utils";
import "./VideoLightbox.css";

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

export type VideoLightboxProps = {
  videos: VideoItem[];
  currentIndex: number;
  onClose: () => void;
  onChangeIndex: (index: number) => void;
  onEditVideo?: (video: VideoItem) => void;
};

export default function VideoLightbox({
  videos,
  currentIndex,
  onClose,
  onChangeIndex,
  onEditVideo
}: VideoLightboxProps) {
  const currentVideo = videos[currentIndex];
  const totalVideos = videos.length;
  const canPrev = currentIndex > 0;
  const canNext = currentIndex < totalVideos - 1;

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const wheelLockRef = useRef(false);

  const [isPlaying, setIsPlaying] = useState(true);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(0.15);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showSpeedMenu, setShowSpeedMenu] = useState(false);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(true);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [indicatorText, setIndicatorText] = useState<string | null>(null);
  const indicatorTimerRef = useRef<number | null>(null);

  const showIndicator = useCallback((text: string) => {
    setIndicatorText(text);
    if (indicatorTimerRef.current) window.clearTimeout(indicatorTimerRef.current);
    indicatorTimerRef.current = window.setTimeout(() => setIndicatorText(null), 1200);
  }, []);

  const handlePrev = useCallback(() => {
    if (canPrev) {
      onChangeIndex(currentIndex - 1);
    } else if (totalVideos > 1) {
      onChangeIndex(totalVideos - 1);
    }
  }, [canPrev, currentIndex, onChangeIndex, totalVideos]);

  const handleNext = useCallback(() => {
    if (canNext) {
      onChangeIndex(currentIndex + 1);
    } else if (totalVideos > 1) {
      onChangeIndex(0);
    }
  }, [canNext, currentIndex, onChangeIndex, totalVideos]);

  // Video playback initialization on index change
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.currentTime = 0;
      setCurrentTime(0);
      videoRef.current.playbackRate = playbackRate;
      videoRef.current.volume = volume;
      videoRef.current.muted = isMuted;
      videoRef.current
        .play()
        .then(() => setIsPlaying(true))
        .catch(() => setIsPlaying(false));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentIndex]);

  // Sync volume and mute changes without resetting playback
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.volume = volume;
      videoRef.current.muted = isMuted;
    }
  }, [volume, isMuted]);

  // Sync playback rate changes without resetting playback
  useEffect(() => {
    if (videoRef.current) {
      videoRef.current.playbackRate = playbackRate;
    }
  }, [playbackRate]);

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

  const handleVolumeSlider = (val: number) => {
    if (videoRef.current) {
      videoRef.current.volume = val;
      if (val > 0 && videoRef.current.muted) {
        videoRef.current.muted = false;
        setIsMuted(false);
      }
    }
    setVolume(val);
    if (val === 0) {
      setIsMuted(true);
    } else {
      setIsMuted(false);
    }
  };

  const handleSeek = useCallback((delta: number) => {
    if (!videoRef.current) return;
    const next = Math.max(0, Math.min(videoRef.current.duration || 0, videoRef.current.currentTime + delta));
    videoRef.current.currentTime = next;
    setCurrentTime(next);
    showIndicator(`${delta > 0 ? "+" : ""}${delta}秒`);
  }, [showIndicator]);

  const toggleFullscreen = useCallback(() => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      containerRef.current.requestFullscreen().catch(() => {});
      setIsFullscreen(true);
    } else {
      document.exitFullscreen().catch(() => {});
      setIsFullscreen(false);
    }
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement;
      const isInput = activeEl instanceof HTMLInputElement || activeEl instanceof HTMLTextAreaElement;
      if (isInput) return;

      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown" || e.key === "PageDown") {
        e.preventDefault();
        handleNext();
      } else if (e.key === "ArrowUp" || e.key === "PageUp") {
        e.preventDefault();
        handlePrev();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        handleSeek(-5);
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        handleSeek(5);
      } else if (e.key === " ") {
        e.preventDefault();
        togglePlay();
      } else if (e.key === "m" || e.key === "M") {
        e.preventDefault();
        toggleMute();
      } else if (e.key === "f" || e.key === "F") {
        e.preventDefault();
        toggleFullscreen();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleNext, handlePrev, handleSeek, onClose, toggleFullscreen, toggleMute, togglePlay]);

  // Lock body scrolling while lightbox is open
  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  // Native wheel listener to prevent background page scroll
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const handleNativeWheel = (e: WheelEvent) => {
      // If user is scrolling the info rail, let sidebar scroll naturally without switching video
      const isInsideInfoRail = e.target instanceof Element && e.target.closest(".video-lightbox-info-rail");
      if (isInsideInfoRail) {
        return;
      }

      e.preventDefault();
      e.stopPropagation();

      if (wheelLockRef.current) return;
      if (Math.abs(e.deltaY) > 25) {
        wheelLockRef.current = true;
        if (e.deltaY > 0) {
          handleNext();
        } else {
          handlePrev();
        }
        window.setTimeout(() => {
          wheelLockRef.current = false;
        }, 350);
      }
    };

    el.addEventListener("wheel", handleNativeWheel, { passive: false });
    return () => {
      el.removeEventListener("wheel", handleNativeWheel);
    };
  }, [handleNext, handlePrev]);

  if (!currentVideo) return null;

  const readySubtitles = currentVideo.subtitle_tracks.filter(
    (t) => t.status === "ready" && t.vtt_url
  );

  return (
    <div
      ref={containerRef}
      className="video-lightbox-backdrop"
      onClick={onClose}
      role="presentation"
    >
      <div
        className="video-lightbox-shell"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Shots 视频放映"
      >
        {/* Top Control Bar */}
        <div className="video-lightbox-topbar">
          <div className="video-lightbox-page-badge">
            <span className="current-pos">{String(currentIndex + 1).padStart(2, "0")}</span>
            <span className="sep">/</span>
            <span className="total-pos">{String(totalVideos).padStart(2, "0")}</span>
            <span className="type-tag type-short">
              <Sparkles size={12} />
              <span>Shots</span>
            </span>
          </div>

          <div className="video-lightbox-actions">
            <button
              className="vlb-action-btn"
              title="在新窗口独立播放 (影院模式)"
              onClick={() => window.open(`#video-play/${currentVideo.id}`, "_blank")}
            >
              <ExternalLink size={15} />
              <span>影院播放</span>
            </button>
            {onEditVideo && (
              <button
                className="vlb-action-btn"
                title="编辑视频信息"
                onClick={() => onEditVideo(currentVideo)}
              >
                <Edit3 size={15} />
                <span>编辑</span>
              </button>
            )}
            <button className="vlb-close-btn" title="关闭 (Esc)" onClick={onClose}>
              <X size={18} />
              <span>关闭</span>
            </button>
          </div>
        </div>

        {/* Main Stage */}
        <div className="video-lightbox-stage">
          {/* Core Player Container */}
          <div className="video-lightbox-player-container" onClick={togglePlay}>
            <video
              ref={videoRef}
              src={currentVideo.stream_url || currentVideo.play_url}
              poster={currentVideo.cover_url ?? undefined}
              playsInline
              loop
              onTimeUpdate={() => {
                if (videoRef.current) {
                  setCurrentTime(videoRef.current.currentTime);
                }
              }}
              onLoadedMetadata={() => {
                if (videoRef.current) {
                  setDuration(videoRef.current.duration);
                }
              }}
              onPlay={() => setIsPlaying(true)}
              onPause={() => setIsPlaying(false)}
            >
              {readySubtitles.map((track) => (
                <track
                  key={track.id}
                  src={track.vtt_url ?? undefined}
                  label={track.label}
                  srcLang={track.language}
                  default={subtitlesEnabled}
                  kind="subtitles"
                />
              ))}
            </video>

            {/* Play/Pause Overlay */}
            {!isPlaying && (
              <div className="video-lightbox-pause-overlay">
                <div className="pause-icon-circle">
                  <Play size={36} fill="currentColor" />
                </div>
              </div>
            )}

            {/* Center Status Pop Indicator */}
            {indicatorText && (
              <div className="video-lightbox-indicator">
                {indicatorText}
              </div>
            )}

            {/* Bottom Minimalist Video Controls */}
            <div className="video-lightbox-controls" onClick={(e) => e.stopPropagation()}>
              {/* Progress Slider */}
              <div
                className="video-lightbox-progress-rail"
                onClick={(e) => {
                  const rect = e.currentTarget.getBoundingClientRect();
                  const clickRatio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
                  if (videoRef.current && duration > 0) {
                    const nextTime = clickRatio * duration;
                    videoRef.current.currentTime = nextTime;
                    setCurrentTime(nextTime);
                  }
                }}
              >
                <div
                  className="video-lightbox-progress-filled"
                  style={{ width: `${duration > 0 ? (currentTime / duration) * 100 : 0}%` }}
                />
              </div>

              <div className="video-lightbox-controls-row">
                <div className="ctrl-left">
                  <button className="ctrl-btn" onClick={togglePlay} title={isPlaying ? "暂停 (空格)" : "播放 (空格)"}>
                    {isPlaying ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" />}
                  </button>

                  {/* Stepless Volume Control with hover slider */}
                  <div className="vlb-volume-wrapper">
                    <button className="ctrl-btn" onClick={toggleMute} title={isMuted ? "取消静音 (M)" : "静音 (M)"}>
                      {isMuted || volume === 0 ? (
                        <VolumeX size={20} />
                      ) : volume < 0.5 ? (
                        <Volume1 size={20} />
                      ) : (
                        <Volume2 size={20} />
                      )}
                    </button>
                    <div className="vlb-volume-slider-box">
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.01"
                        value={isMuted ? 0 : volume}
                        onChange={(e) => handleVolumeSlider(parseFloat(e.target.value))}
                        className="vlb-volume-range"
                        style={{
                          background: `linear-gradient(to right, var(--accent) ${(isMuted ? 0 : volume) * 100}%, rgba(255, 255, 255, 0.3) ${(isMuted ? 0 : volume) * 100}%)`
                        }}
                        title={`音量: ${Math.round((isMuted ? 0 : volume) * 100)}%`}
                      />
                    </div>
                  </div>

                  <span className="ctrl-time">
                    {formatTime(currentTime)} / {formatTime(duration || currentVideo.duration_seconds || 0)}
                  </span>
                </div>

                <div className="ctrl-right">
                  {readySubtitles.length > 0 && (
                    <button
                      className={`ctrl-btn ${subtitlesEnabled ? "active" : ""}`}
                      onClick={() => setSubtitlesEnabled(!subtitlesEnabled)}
                      title={subtitlesEnabled ? "关闭中文字幕" : "开启中文字幕"}
                    >
                      <Subtitles size={20} />
                    </button>
                  )}

                  <div className="ctrl-speed-wrap">
                    <button
                      className="ctrl-btn speed-btn"
                      onClick={() => setShowSpeedMenu(!showSpeedMenu)}
                      title="倍速选择"
                    >
                      {playbackRate}x
                    </button>
                    {showSpeedMenu && (
                      <div className="speed-dropdown">
                        {[2.0, 1.5, 1.25, 1.0, 0.5].map((rate) => (
                          <button
                            key={rate}
                            className={`speed-option ${playbackRate === rate ? "active" : ""}`}
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

                  <button className="ctrl-btn" onClick={toggleFullscreen} title="全屏 (F)">
                    {isFullscreen ? <Minimize2 size={20} /> : <Maximize2 size={20} />}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Video Info Rail matching PictureShow style */}
        <aside className="video-lightbox-info-rail">
          <div className="vlb-info-head">
            <h2 className="vlb-title" title={currentVideo.title}>
              {currentVideo.title}
            </h2>
            {currentVideo.description ? (
              <p className="vlb-description">{currentVideo.description}</p>
            ) : (
              <p className="vlb-description-empty">暂无视频简介</p>
            )}
          </div>

          <div className="vlb-meta-section">
            <div className="vlb-section-title">UP主</div>
            <div className="vlb-up-list">
              {currentVideo.people.map((person) => (
                <div className="vlb-up-pill" key={person.id}>
                  {person.avatar_url ? (
                    <img src={person.avatar_url} alt={person.name} />
                  ) : (
                    <span className="fallback-av">{person.name.slice(0, 1)}</span>
                  )}
                  <span className="up-name">{person.name}</span>
                </div>
              ))}
              {currentVideo.people.length === 0 && (
                <span className="vlb-empty-hint">未关联 UP 主</span>
              )}
            </div>

            <div className="vlb-section-title">分区标签</div>
            <div className="vlb-tags-cloud">
              {currentVideo.category_tags.map((tag) => (
                <span key={tag.id} className="soft-chip active">
                  #{tag.name}
                </span>
              ))}
              {currentVideo.category_tags.length === 0 && (
                <span className="vlb-empty-hint">暂无标签</span>
              )}
            </div>

            <div className="vlb-section-title">视频属性</div>
            <div className="vlb-meta-table">
              <div className="vlb-meta-row">
                <span className="label">视频形态</span>
                <span className="value">
                  {currentVideo.video_type === "short" ? "短视频" : "长视频"}
                </span>
              </div>
              <div className="vlb-meta-row">
                <span className="label">时长</span>
                <span className="value">
                  {currentVideo.duration_seconds
                    ? formatDurationSeconds(currentVideo.duration_seconds)
                    : "未知"}
                </span>
              </div>
              <div className="vlb-meta-row">
                <span className="label">文件大小</span>
                <span className="value">{formatBytes(currentVideo.size_bytes)}</span>
              </div>
              <div className="vlb-meta-row">
                <span className="label">分辨率</span>
                <span className="value">
                  {currentVideo.width && currentVideo.height
                    ? `${currentVideo.width} × ${currentVideo.height}`
                    : "自适应"}
                </span>
              </div>
              <div className="vlb-meta-row">
                <span className="label">上传时间</span>
                <span className="value">{formatDate(currentVideo.created_at)}</span>
              </div>
            </div>
          </div>

          <div className="vlb-shortcuts-box">
            <span className="box-title">快捷键提示</span>
            <div className="vlb-shortcut-grid">
              <span><b>↑ / ↓</b> 切换视频</span>
              <span><b>← / →</b> 快退/快进</span>
              <span><b>空格</b> 播放/暂停</span>
              <span><b>M</b> 静音切换</span>
              <span><b>F</b> 全屏/退出</span>
              <span><b>Esc</b> 关闭灯箱</span>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
