import React, { useRef, useState, useEffect, useCallback, MouseEvent as ReactMouseEvent } from "react";
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
  
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
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

  const RATE_OPTIONS = [2.0, 1.5, 1.25, 1.0, 0.5];

  useEffect(() => {
    setSubtitlesEnabled(subtitles.length > 0);
  }, [subtitles]);

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
  }, [resetControlsTimeout, isMuted]);

  const handleProgressClick = (e: ReactMouseEvent<HTMLDivElement>) => {
    if (!videoRef.current || !duration) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const pos = (e.clientX - rect.left) / rect.width;
    videoRef.current.currentTime = pos * duration;
  };

  const handleVideoTimeUpdate = () => {
    if (!videoRef.current) return;
    if (!isDraggingProgress) {
      setCurrentTime(videoRef.current.currentTime);
    }
    if (videoRef.current.buffered.length > 0) {
      setBuffered(videoRef.current.buffered.end(videoRef.current.buffered.length - 1));
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
        onClick={togglePlay}
        onTimeUpdate={handleVideoTimeUpdate}
        onDurationChange={() => setDuration(videoRef.current?.duration || 0)}
        onLoadedMetadata={() => { if (videoRef.current) videoRef.current.volume = 0.2; }}
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
        <div className="bili-progress-area" onClick={handleProgressClick}>
          <div className="bili-progress-bar-bg" />
          <div className="bili-progress-bar-buf" style={{ width: `${duration ? (buffered / duration) * 100 : 0}%` }} />
          <div className="bili-progress-bar-cur" style={{ width: `${duration ? (currentTime / duration) * 100 : 0}%` }} />
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
            <div className="bili-time-display">
              {formatTime(currentTime)} / {formatTime(duration)}
            </div>
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
