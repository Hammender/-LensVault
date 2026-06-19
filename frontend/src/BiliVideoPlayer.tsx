import React, { useRef, useState, useEffect, useCallback, PointerEvent as ReactPointerEvent } from "react";
import { Maximize, Minimize, Pause, Play, Volume2, VolumeX } from "lucide-react";
import "./BiliVideoPlayer.css";

function formatTime(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "00:00";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) {
    return `${h}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }
  return `${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
}

interface BiliVideoPlayerProps {
  src: string;
  poster?: string;
  subtitles?: Array<{
    src: string;
    label: string;
    srclang: string;
  }>;
}

export default function BiliVideoPlayer({ src, poster, subtitles = [] }: BiliVideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const rateMenuRef = useRef<HTMLDivElement>(null);
  const progressCurrentRef = useRef<HTMLDivElement>(null);
  const progressBufferedRef = useRef<HTMLDivElement>(null);
  
  const [isPlaying, setIsPlaying] = useState(false);
  const [duration, setDuration] = useState(0);
  const [timeLabel, setTimeLabel] = useState(`${formatTime(0)} / ${formatTime(0)}`);
  const [volume, setVolume] = useState(0.2);
  const [isMuted, setIsMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showRateMenu, setShowRateMenu] = useState(false);
  const [subtitlesEnabled, setSubtitlesEnabled] = useState(subtitles.length > 0);
  const subtitleKey = subtitles.map((track) => track.src).join("|");
  
  const [showControls, setShowControls] = useState(true);
  const controlsTimeoutRef = useRef<number | null>(null);
  
  const [indicatorText, setIndicatorText] = useState<string | null>(null);
  const indicatorTimeoutRef = useRef<number | null>(null);

  const [isFastForwarding, setIsFastForwarding] = useState(false);
  const longPressTimerRef = useRef<number | null>(null);
  const longPressActiveRef = useRef(false);
  
  const [isDraggingProgress, setIsDraggingProgress] = useState(false);
  const isDraggingProgressRef = useRef(false);
  const seekStartedAtRef = useRef<number | null>(null);
  const seekTargetRef = useRef<number | null>(null);
  const pendingSeekTimeRef = useRef<number | null>(null);
  const currentTimeRef = useRef(0);
  const bufferedTimeRef = useRef(0);
  const durationRef = useRef(0);
  const lastTimeDisplayUpdateRef = useRef(0);
  const animationFrameRef = useRef<number | null>(null);
  const debugVideoEvents = typeof window !== "undefined" && window.localStorage.getItem("pictureShowVideoDebug") === "1";

  const RATE_OPTIONS = [2.0, 1.5, 1.25, 1.0, 0.5];

  const logVideoEvent = (eventName: string, video: HTMLVideoElement) => {
    if (!debugVideoEvents) return;
    console.info(`[video-playback:custom] ${eventName}`, {
      currentTime: Number(video.currentTime.toFixed(3)),
      duration: Number.isFinite(video.duration) ? Number(video.duration.toFixed(3)) : null,
      readyState: video.readyState,
      networkState: video.networkState,
      src
    });
  };

  const updateProgressDom = useCallback((time: number, bufferedTime = bufferedTimeRef.current, forceTimeText = false) => {
    currentTimeRef.current = Number.isFinite(time) ? Math.max(time, 0) : 0;
    bufferedTimeRef.current = Number.isFinite(bufferedTime) ? Math.max(bufferedTime, 0) : 0;
    const safeDuration = durationRef.current;
    const currentRatio = safeDuration > 0 ? Math.min(Math.max(currentTimeRef.current / safeDuration, 0), 1) : 0;
    const bufferedRatio = safeDuration > 0 ? Math.min(Math.max(bufferedTimeRef.current / safeDuration, 0), 1) : 0;
    if (progressCurrentRef.current) {
      progressCurrentRef.current.style.width = `${currentRatio * 100}%`;
    }
    if (progressBufferedRef.current) {
      progressBufferedRef.current.style.width = `${bufferedRatio * 100}%`;
    }
    const now = performance.now();
    if (forceTimeText || now - lastTimeDisplayUpdateRef.current >= 250) {
      setTimeLabel(`${formatTime(currentTimeRef.current)} / ${formatTime(safeDuration)}`);
      lastTimeDisplayUpdateRef.current = now;
    }
  }, []);

  const scheduleProgressDomUpdate = useCallback((time: number, bufferedTime = bufferedTimeRef.current, forceTimeText = false) => {
    if (animationFrameRef.current !== null) {
      window.cancelAnimationFrame(animationFrameRef.current);
    }
    animationFrameRef.current = window.requestAnimationFrame(() => {
      animationFrameRef.current = null;
      updateProgressDom(time, bufferedTime, forceTimeText);
    });
  }, [updateProgressDom]);

  useEffect(() => {
    setSubtitlesEnabled(subtitles.length > 0);
  }, [subtitles]);

  useEffect(() => {
    return () => {
      if (animationFrameRef.current !== null) {
        window.cancelAnimationFrame(animationFrameRef.current);
      }
    };
  }, []);

  useEffect(() => {
    currentTimeRef.current = 0;
    bufferedTimeRef.current = 0;
    durationRef.current = 0;
    setDuration(0);
    setTimeLabel(`${formatTime(0)} / ${formatTime(0)}`);
    updateProgressDom(0, 0, true);
  }, [src, updateProgressDom]);

  const showIndicator = (text: string) => {
    setIndicatorText(text);
    if (indicatorTimeoutRef.current) window.clearTimeout(indicatorTimeoutRef.current);
    indicatorTimeoutRef.current = window.setTimeout(() => setIndicatorText(null), 1500);
  };

  const resetControlsTimeout = useCallback(() => {
    setShowControls(true);
    if (controlsTimeoutRef.current) window.clearTimeout(controlsTimeoutRef.current);
    controlsTimeoutRef.current = window.setTimeout(() => {
      if (isPlaying) setShowControls(false);
    }, 2500);
  }, [isPlaying]);

  useEffect(() => {
    resetControlsTimeout();
    return () => {
      if (controlsTimeoutRef.current) window.clearTimeout(controlsTimeoutRef.current);
    };
  }, [isPlaying, resetControlsTimeout]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(!!document.fullscreenElement);
    };
    document.addEventListener("fullscreenchange", handleFullscreenChange);
    return () => document.removeEventListener("fullscreenchange", handleFullscreenChange);
  }, []);

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (rateMenuRef.current && !rateMenuRef.current.contains(e.target as Node)) {
        setShowRateMenu(false);
      }
    };
    if (showRateMenu) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [showRateMenu]);

  const togglePlay = () => {
    if (videoRef.current) {
      if (videoRef.current.paused) {
        videoRef.current.play().catch(() => {});
      } else {
        videoRef.current.pause();
      }
    }
  };

  const toggleFullscreen = async () => {
    if (!containerRef.current) return;
    if (!document.fullscreenElement) {
      await containerRef.current.requestFullscreen().catch(() => {});
    } else {
      if (document.exitFullscreen) {
        await document.exitFullscreen().catch(() => {});
      }
    }
  };

  const handleVolumeChange = (delta: number) => {
    if (videoRef.current) {
      let newVol = videoRef.current.volume + delta;
      newVol = Math.max(0, Math.min(1, newVol));
      videoRef.current.volume = newVol;
      if (newVol > 0 && videoRef.current.muted) {
        setIsMuted(false);
        videoRef.current.muted = false;
      }
      setVolume(newVol);
      showIndicator(`音量: ${Math.round(newVol * 100)}%`);
    }
  };

  useEffect(() => {
    const handleWheelNative = (e: WheelEvent) => {
      e.preventDefault();
      handleVolumeChange(e.deltaY < 0 ? 0.05 : -0.05);
    };

    const el = containerRef.current;
    if (el) {
      el.addEventListener('wheel', handleWheelNative, { passive: false });
    }
    return () => {
      if (el) {
        el.removeEventListener('wheel', handleWheelNative);
      }
    };
  }, []); // isMuted/volume updates correctly via videoRef.current properties

  const seek = (delta: number) => {
    if (videoRef.current && Number.isFinite(videoRef.current.duration)) {
      const nextTime = Math.min(Math.max(videoRef.current.currentTime + delta, 0), videoRef.current.duration);
      videoRef.current.currentTime = nextTime;
      updateProgressDom(nextTime, bufferedTimeRef.current, true);
      showIndicator(`${delta > 0 ? '快进' : '快退'} ${Math.abs(delta)}秒`);
    }
  };

  const startFastForward = () => {
    if (!videoRef.current || longPressActiveRef.current) return;
    longPressActiveRef.current = true;
    setIsFastForwarding(true);
    videoRef.current.playbackRate = 3;
    showIndicator("3x 快进中");
  };

  const stopFastForward = () => {
    if (!videoRef.current || !longPressActiveRef.current) return;
    longPressActiveRef.current = false;
    setIsFastForwarding(false);
    videoRef.current.playbackRate = playbackRate;
    setIndicatorText(null);
  };

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Don't intercept if typing in input
      if (e.target instanceof HTMLElement && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA")) return;

      resetControlsTimeout();

      switch (e.key) {
        case " ":
          e.preventDefault();
          togglePlay();
          break;
        case "ArrowUp":
          e.preventDefault();
          handleVolumeChange(0.05);
          break;
        case "ArrowDown":
          e.preventDefault();
          handleVolumeChange(-0.05);
          break;
        case "f":
        case "F":
          e.preventDefault();
          void toggleFullscreen();
          break;
        case "m":
        case "M":
          e.preventDefault();
          if (videoRef.current) {
            videoRef.current.muted = !videoRef.current.muted;
            setIsMuted(videoRef.current.muted);
            showIndicator(videoRef.current.muted ? "已静音" : "取消静音");
          }
          break;
        case "ArrowRight":
        case "ArrowLeft":
          e.preventDefault();
          if (e.repeat) return;
          if (e.key === "ArrowRight") {
            if (longPressTimerRef.current) window.clearTimeout(longPressTimerRef.current);
            longPressTimerRef.current = window.setTimeout(startFastForward, 500);
          } else {
            seek(e.shiftKey ? -30 : -10);
          }
          break;
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") {
        if (longPressTimerRef.current) {
          window.clearTimeout(longPressTimerRef.current);
          longPressTimerRef.current = null;
        }
        if (longPressActiveRef.current) {
          stopFastForward();
        } else {
          seek(e.shiftKey ? 30 : 10);
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [resetControlsTimeout, isMuted, updateProgressDom]);

  const getProgressTime = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!durationRef.current) return null;
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = Math.min(Math.max((e.clientX - rect.left) / rect.width, 0), 1);
    return pos * durationRef.current;
  };

  const updateProgressPreview = (e: ReactPointerEvent<HTMLDivElement>) => {
    const nextTime = getProgressTime(e);
    if (nextTime === null) return;
    pendingSeekTimeRef.current = nextTime;
    updateProgressDom(nextTime, bufferedTimeRef.current, true);
    setShowControls(true);
  };

  const handleProgressPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!videoRef.current || !durationRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    e.currentTarget.setPointerCapture(e.pointerId);
    isDraggingProgressRef.current = true;
    setIsDraggingProgress(true);
    updateProgressPreview(e);
  };

  const handleProgressPointerMove = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!isDraggingProgressRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    updateProgressPreview(e);
  };

  const commitProgressSeek = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!isDraggingProgressRef.current || !videoRef.current) return;
    e.preventDefault();
    e.stopPropagation();
    updateProgressPreview(e);
    const nextTime = pendingSeekTimeRef.current;
    if (nextTime !== null) {
      videoRef.current.currentTime = nextTime;
    }
    pendingSeekTimeRef.current = null;
    isDraggingProgressRef.current = false;
    setIsDraggingProgress(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId)) {
      e.currentTarget.releasePointerCapture(e.pointerId);
    }
  };

  const cancelProgressSeek = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (!isDraggingProgressRef.current) return;
    e.stopPropagation();
    pendingSeekTimeRef.current = null;
    isDraggingProgressRef.current = false;
    setIsDraggingProgress(false);
    updateProgressDom(videoRef.current?.currentTime ?? currentTimeRef.current, bufferedTimeRef.current, true);
  };

  const handleVideoTimeUpdate = () => {
    if (!videoRef.current) return;
    const video = videoRef.current;
    let nextBuffered = bufferedTimeRef.current;
    if (video.buffered.length > 0) {
      let bufferedEnd = 0;
      for (let index = 0; index < video.buffered.length; index += 1) {
        const start = video.buffered.start(index);
        const end = video.buffered.end(index);
        if (video.currentTime >= start && video.currentTime <= end) {
          bufferedEnd = end;
          break;
        }
        if (end <= video.currentTime) {
          bufferedEnd = Math.max(bufferedEnd, end);
        }
      }
      nextBuffered = bufferedEnd;
    }
    if (!isDraggingProgressRef.current) {
      scheduleProgressDomUpdate(video.currentTime, nextBuffered);
    } else {
      bufferedTimeRef.current = nextBuffered;
    }
  };

  const toggleMute = () => {
    if (videoRef.current) {
      videoRef.current.muted = !videoRef.current.muted;
      setIsMuted(videoRef.current.muted);
    }
  };

  const handleRateChange = (rate: number) => {
    if (videoRef.current) {
      videoRef.current.playbackRate = rate;
      setPlaybackRate(rate);
      setShowRateMenu(false);
      showIndicator(`倍速: ${rate}x`);
    }
  };

  useEffect(() => {
    if (!videoRef.current) return;
    Array.from(videoRef.current.textTracks).forEach((track, index) => {
      track.mode = subtitlesEnabled && index === 0 ? "showing" : "disabled";
    });
  }, [subtitlesEnabled, subtitleKey]);

  const toggleSubtitles = () => {
    if (subtitles.length === 0) return;
    setSubtitlesEnabled((current) => {
      const next = !current;
      showIndicator(next ? "字幕已开启" : "字幕已关闭");
      return next;
    });
  };

  return (
    <div 
      ref={containerRef}
      className={`bili-player-container ${!showControls ? 'hide-cursor' : ''} ${isFullscreen ? 'fullscreen' : ''}`}
      onMouseMove={resetControlsTimeout}
      onMouseLeave={() => { if (isPlaying) setShowControls(false); }}
      onDoubleClick={toggleFullscreen}
    >
      <video
        ref={videoRef}
        src={src}
        poster={poster}
        className="bili-video-el"
        preload="auto"
        onClick={togglePlay}
        onLoadStart={(event) => logVideoEvent("loadstart", event.currentTarget)}
        onTimeUpdate={handleVideoTimeUpdate}
        onDurationChange={() => {
          const nextDuration = videoRef.current?.duration || 0;
          durationRef.current = nextDuration;
          setDuration(nextDuration);
          updateProgressDom(videoRef.current?.currentTime ?? currentTimeRef.current, bufferedTimeRef.current, true);
        }}
        onLoadedMetadata={(event) => {
          event.currentTarget.volume = 0.2;
          durationRef.current = Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : 0;
          setDuration(durationRef.current);
          updateProgressDom(event.currentTarget.currentTime, bufferedTimeRef.current, true);
          logVideoEvent("loadedmetadata", event.currentTarget);
        }}
        onWaiting={(event) => logVideoEvent("waiting", event.currentTarget)}
        onCanPlay={(event) => logVideoEvent("canplay", event.currentTarget)}
        onSeeking={(event) => {
          seekStartedAtRef.current = performance.now();
          seekTargetRef.current = event.currentTarget.currentTime;
          logVideoEvent("seeking", event.currentTarget);
        }}
        onSeeked={(event) => {
          const startedAt = seekStartedAtRef.current;
          const target = seekTargetRef.current;
          if (debugVideoEvents) {
            console.info("[video-playback:custom] seeked", {
              target: target === null ? null : Number(target.toFixed(3)),
              currentTime: Number(event.currentTarget.currentTime.toFixed(3)),
              elapsedMs: startedAt === null ? null : Math.round(performance.now() - startedAt),
              readyState: event.currentTarget.readyState,
              networkState: event.currentTarget.networkState,
              src
            });
          }
          seekStartedAtRef.current = null;
          seekTargetRef.current = null;
          updateProgressDom(event.currentTarget.currentTime, bufferedTimeRef.current, true);
        }}
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        playsInline
      >
        {subtitles.map((track, index) => (
          <track
            key={`${track.src}-${track.srclang}`}
            src={track.src}
            kind="subtitles"
            srcLang={track.srclang}
            label={track.label}
            default={index === 0}
          />
        ))}
      </video>

      {indicatorText && (
        <div className="bili-indicator">
          {indicatorText}
        </div>
      )}

      {isFastForwarding && (
        <div className="bili-fast-forward-hint">
          <span>{">>"}</span> 3x
        </div>
      )}

      <div className={`bili-controls-overlay ${showControls ? 'show' : ''}`}>
        <div
          className={`bili-progress-area${isDraggingProgress ? " dragging" : ""}`}
          onPointerDown={handleProgressPointerDown}
          onPointerMove={handleProgressPointerMove}
          onPointerUp={commitProgressSeek}
          onPointerCancel={cancelProgressSeek}
        >
          <div className="bili-progress-bar-bg" />
          <div className="bili-progress-bar-buf" ref={progressBufferedRef} />
          <div className="bili-progress-bar-cur" ref={progressCurrentRef} />
        </div>
        
        <div className="bili-controls-bottom">
          <div className="bili-controls-left">
            <button className="bili-icon-btn" onClick={togglePlay}>
              {isPlaying ? (
                <Pause size={24} aria-hidden="true" />
              ) : (
                <Play size={24} aria-hidden="true" />
              )}
            </button>
            <div className="bili-time-display">{timeLabel}</div>
          </div>
          
          <div className="bili-controls-right">
            {subtitles.length > 0 && (
              <button
                className={`bili-icon-btn bili-subtitle-btn${subtitlesEnabled ? " active" : ""}`}
                onClick={toggleSubtitles}
                title={subtitlesEnabled ? "关闭字幕" : "开启字幕"}
              >
                <span>CC</span>
              </button>
            )}
            <div className="bili-rate-wrapper" ref={rateMenuRef}>
              <button className="bili-icon-btn bili-rate-btn" onClick={() => setShowRateMenu(!showRateMenu)} title="倍速">
                <span className="bili-rate-value">{playbackRate}x</span>
              </button>
              {showRateMenu && (
                <div className="bili-rate-menu">
                  {RATE_OPTIONS.map((rate) => (
                    <button
                      key={rate}
                      className={`bili-rate-option${rate === playbackRate ? ' active' : ''}`}
                      onClick={() => handleRateChange(rate)}
                    >
                      {rate}x
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button className="bili-icon-btn" onClick={toggleMute} title="静音 (M)">
              {isMuted || volume === 0 ? (
                <VolumeX size={24} aria-hidden="true" />
              ) : (
                <Volume2 size={24} aria-hidden="true" />
              )}
            </button>
            <button className="bili-icon-btn" onClick={toggleFullscreen} title="全屏 (F)">
              {isFullscreen ? (
                <Minimize size={24} aria-hidden="true" />
              ) : (
                <Maximize size={24} aria-hidden="true" />
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
