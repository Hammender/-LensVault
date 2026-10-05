from __future__ import annotations

import atexit
import bisect
import json
import math
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VideoFrame:
    pts: int
    seconds: float
    keyframe: bool


@dataclass
class CachedVideo:
    directory: tempfile.TemporaryDirectory
    path: Path
    frames: list[VideoFrame]
    times: list[float]
    start_seconds: float
    used_at: float


class AcquisitionFrameService:
    """按真实时间戳选帧；原视频和少量 PNG 仅缓存在有界临时目录中。"""

    def __init__(self, storage, settings) -> None:
        self.storage = storage
        self.settings = settings
        self._lock = threading.RLock()
        self._videos: OrderedDict[tuple, CachedVideo] = OrderedDict()
        self._timer: threading.Timer | None = None
        self._closed = False
        atexit.register(self.close)
        self._schedule_cleanup()

    def _schedule_cleanup(self) -> None:
        self._timer = threading.Timer(60, self._expire)
        self._timer.daemon = True
        self._timer.start()

    def _expire(self) -> None:
        with self._lock:
            self._prune()
            if not self._closed:
                self._schedule_cleanup()

    def _prune(self) -> None:
        for key, video in list(self._videos.items()):
            if time.monotonic() - video.used_at > 300:
                self._videos.pop(key).directory.cleanup()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
            for video in self._videos.values():
                video.directory.cleanup()
            self._videos.clear()

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(command, capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("视频帧处理超时，请重试或选择较短的视频") from exc
        except OSError as exc:
            raise ValueError("视频选帧工具不可用，请检查 FFmpeg 和 FFprobe 配置") from exc
        if result.returncode:
            raise ValueError("视频帧解码失败，请检查原视频是否完整")
        return result

    def _video(self, asset) -> CachedVideo:
        self._prune()
        key = (asset.workspace_id, asset.id, asset.sha256, asset.object_key)
        cached = self._videos.get(key)
        if cached:
            cached.used_at = time.monotonic()
            self._videos.move_to_end(key)
            return cached
        # 同时最多缓存两个视频，总原文件预算 2 GiB；大视频仍可处理，但不与其他视频共存。
        while self._videos and (len(self._videos) >= 2 or
                sum(v.path.stat().st_size for v in self._videos.values()) + asset.size_bytes > 2 * 1024**3):
            self._videos.popitem(last=False)[1].directory.cleanup()
        directory = tempfile.TemporaryDirectory(prefix="acq-frames-")
        path = Path(directory.name) / ("source" + (Path(asset.filename).suffix or ".mp4"))
        try:
            stream = self.storage.get_stream(asset.object_key)
            try:
                with path.open("wb") as target:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        target.write(chunk)
            finally:
                stream.close()
                if hasattr(stream, "release_conn"):
                    stream.release_conn()
            result = self._run([
                self.settings.ffprobe_path, "-v", "error", "-select_streams", "v:0",
                "-show_frames", "-show_format", "-show_streams", "-show_entries",
                "frame=best_effort_timestamp,best_effort_timestamp_time,key_frame:format=start_time:stream=start_time",
                "-of", "json", str(path),
            ])
            info = json.loads(result.stdout)
            frames = [VideoFrame(int(f["best_effort_timestamp"]), float(f["best_effort_timestamp_time"]),
                                 bool(f.get("key_frame"))) for f in info.get("frames", [])]
            if not frames or any(not math.isfinite(f.seconds) for f in frames):
                raise ValueError("视频没有可定位的画面")
            if any(a.seconds >= b.seconds for a, b in zip(frames, frames[1:])):
                raise ValueError("视频帧时间戳异常，无法保证精确选帧")
            start = float(info.get("format", {}).get("start_time") or
                          info.get("streams", [{}])[0].get("start_time") or 0)
            cached = CachedVideo(directory, path, frames, [f.seconds - start for f in frames],
                                 start, time.monotonic())
            self._videos[key] = cached
            return cached
        except Exception:
            directory.cleanup()
            raise

    @staticmethod
    def _index(video: CachedVideo, seconds: float, index: int | None, direction: int) -> int:
        if index is None:
            index = max(0, bisect.bisect_right(video.times, seconds + 0.000001) - 1)
        if index < 0 or index >= len(video.frames):
            raise ValueError("视频帧不存在，请重新定位")
        return max(0, min(len(video.frames) - 1, index + direction))

    def locate(self, asset, seconds: float = 0, index: int | None = None, direction: int = 0) -> dict:
        with self._lock:
            video = self._video(asset)
            index = self._index(video, seconds, index, direction)
            return {"frame_index": index, "time_seconds": max(0, video.times[index]),
                    "total_frames": len(video.frames), "source_sha256": asset.sha256}

    def extract(self, asset, seconds: float = 0, index: int | None = None) -> tuple[dict, bytes]:
        with self._lock:
            video = self._video(asset)
            index = self._index(video, seconds, index, 0)
            frame = video.frames[index]
            output = Path(video.directory.name) / f"{index}.png"
            if not output.exists():
                key_index = index
                while key_index > 0 and not video.frames[key_index].keyframe:
                    key_index -= 1
                seek = max(0, video.frames[key_index].seconds - video.start_seconds)
                temporary = output.with_name(f"partial-{index}.png")
                try:
                    self._run([
                        self.settings.ffmpeg_path, "-v", "error", "-nostdin", "-y", "-copyts",
                        "-ss", f"{seek:.9f}", "-i", str(video.path), "-map", "0:v:0",
                        "-vf", f"select=eq(pts\\,{frame.pts})", "-fps_mode", "passthrough",
                        "-frames:v", "1", "-c:v", "png", str(temporary),
                    ])
                    if not temporary.is_file() or not temporary.stat().st_size:
                        raise ValueError("未能解码选中的帧，请重新定位后再截图")
                    temporary.replace(output)
                finally:
                    temporary.unlink(missing_ok=True)
            payload = output.read_bytes()
            # 每个视频最多保留八张原尺寸帧，避免长时间逐帧操作累积文件。
            images = sorted(Path(video.directory.name).glob("*.png"), key=lambda p: p.stat().st_mtime)
            for old in images[:-8]:
                if old != output:
                    old.unlink(missing_ok=True)
            return self.locate(asset, index=index), payload
