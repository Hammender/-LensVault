import React, { useRef, useState, useEffect, useCallback, MouseEvent as ReactMouseEvent } from "react";
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
}

export default function BiliVideoPlayer({ src, poster }: BiliVideoPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const rateMenuRef = useRef<HTMLDivElement>(null);
  
  const [isPlaying, setIsPlaying] = useState(false);
  const [currentTime, setCurrentTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [isMuted, setIsMuted] = useState(false);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showRateMenu, setShowRateMenu] = useState(false);
  
  const [showControls, setShowControls] = useState(true);
  const controlsTimeoutRef = useRef<number | null>(null);
  
  const [indicatorText, setIndicatorText] = useState<string | null>(null);
  const indicatorTimeoutRef = useRef<number | null>(null);

  const [isFastForwarding, setIsFastForwarding] = useState(false);
  const longPressTimerRef = useRef<number | null>(null);
  const longPressActiveRef = useRef(false);
  
  const [isDraggingProgress, setIsDraggingProgress] = useState(false);

  const RATE_OPTIONS = [2.0, 1.5, 1.25, 1.0, 0.5];

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
        onPlay={() => setIsPlaying(true)}
        onPause={() => setIsPlaying(false)}
        onEnded={() => setIsPlaying(false)}
        playsInline
      />

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
                <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>
              ) : (
                <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>
              )}
            </button>
            <div className="bili-time-display">
              {formatTime(currentTime)} / {formatTime(duration)}
            </div>
          </div>
          
          <div className="bili-controls-right">
            <div className="bili-rate-wrapper" ref={rateMenuRef}>
              <button className="bili-icon-btn bili-rate-btn" onClick={() => setShowRateMenu(!showRateMenu)} title="倍速">
                <span style={{ fontSize: '13px', fontWeight: 700 }}>{playbackRate}x</span>
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
                <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3L3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4L9.91 6.09 12 8.18V4z"/></svg>
              ) : (
                <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/></svg>
              )}
            </button>
            <button className="bili-icon-btn" onClick={toggleFullscreen} title="全屏 (F)">
              {isFullscreen ? (
                <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M5 16h3v3h2v-5H5v2zm3-8H5v2h5V5H8v3zm6 11h2v-3h3v-2h-5v5zm2-11V5h-2v5h5V8h-3z"/></svg>
              ) : (
                <svg viewBox="0 0 24 24" width="24" height="24"><path fill="currentColor" d="M7 14H5v5h5v-2H7v-3zm-2-4h2V7h3V5H5v5zm12 7h-3v2h5v-5h-2v3zM14 5v2h3v3h2V5h-5z"/></svg>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
