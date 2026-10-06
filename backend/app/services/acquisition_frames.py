from __future__ import annotations

import atexit
import bisect
from io import BytesIO
import json
import math
import subprocess
import tempfile
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageCms


COLOR_CONVERSION_VERSION = "srgb-v1"
_SRGB_PROFILE = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _source_color(stream: dict) -> dict:
    """优先使用原片颜色标记；未标记的 SDR 视频按浏览器惯例解释为 BT.709。"""
    raw = {
        "matrix": stream.get("color_space"),
        "transfer": stream.get("color_transfer"),
        "primaries": stream.get("color_primaries"),
        "range": stream.get("color_range"),
    }
    if raw["transfer"] in {"smpte2084", "arib-std-b67"} or raw["primaries"] == "bt2020":
        raise ValueError("暂不支持 HDR 视频截图的 sRGB 转换")
    allowed = {
        "matrix": {"bt709", "bt470bg", "smpte170m"},
        "transfer": {"bt709", "smpte170m", "iec61966-2-1"},
        "primaries": {"bt709", "bt470bg", "smpte170m"},
        "range": {"tv", "pc"},
    }
    defaults = {"matrix": "bt709", "transfer": "bt709", "primaries": "bt709", "range": "tv"}
    values = {}
    assumed = []
    for field, value in raw.items():
        if value in {None, "unknown", "unspecified"}:
            values[field] = defaults[field]
            assumed.append(field)
        elif value in allowed[field]:
            values[field] = value
        else:
            raise ValueError(f"视频颜色标记不受支持（{field}: {value}）")
    return {"version": COLOR_CONVERSION_VERSION, "source": values, "assumed": assumed, "output": "sRGB"}


def _color_filter(color: dict) -> str:
    source = color["source"]
    return (
        "colorspace="
        f"ispace={source['matrix']}:itrc={source['transfer']}:iprimaries={source['primaries']}:"
        f"irange={source['range']}:space=bt709:trc=srgb:primaries=bt709:range=pc:format=yuv444p12,"
        "scale=in_color_matrix=bt709:in_range=pc:out_range=pc,format=rgb24"
    )


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
    color_conversion: dict
    in_use: int = 0


def _probe_frames(info: dict) -> list[VideoFrame]:
    frames = []
    for raw in info.get("frames") or []:
        pts = raw.get("best_effort_timestamp")
        seconds = raw.get("best_effort_timestamp_time")
        if pts in {None, "N/A"} or seconds in {None, "N/A"}:
            continue
        try:
            parsed = VideoFrame(int(pts), float(seconds), bool(raw.get("key_frame")))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(parsed.seconds):
            continue
        frames.append(parsed)
    if not frames:
        raise ValueError("视频没有可定位的画面")
    if any(a.seconds >= b.seconds for a, b in zip(frames, frames[1:])):
        raise ValueError("视频帧时间戳异常，无法保证精确选帧")
    return frames


class AcquisitionFrameService:
    """按真实时间戳选帧；原视频和少量 PNG 仅缓存在有界临时目录中。"""

    def __init__(self, storage, settings) -> None:
        self.storage = storage
        self.settings = settings
        self._lock = threading.RLock()
        self._videos: OrderedDict[tuple, CachedVideo] = OrderedDict()
        self._inflight: dict[tuple, threading.Event] = {}
        self._work_locks: dict[tuple, threading.RLock] = {}
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
            if video.in_use or time.monotonic() - video.used_at <= 300:
                continue
            self._videos.pop(key).directory.cleanup()
            self._work_locks.pop(key, None)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            if self._timer:
                self._timer.cancel()
            waiting = list(self._inflight.values())
            self._inflight.clear()
            for video in self._videos.values():
                video.directory.cleanup()
            self._videos.clear()
            self._work_locks.clear()
        for event in waiting:
            event.set()

    @staticmethod
    def _run(command: list[str]) -> subprocess.CompletedProcess:
        try:
            result = subprocess.run(command, capture_output=True, timeout=120, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("视频帧处理超时，请重试或选择较短的视频") from exc
        except OSError as exc:
            raise ValueError("视频选帧工具不可用，请检查 FFmpeg 和 FFprobe 配置") from exc
        if result.returncode:
            if b"No such filter: 'colorspace'" in result.stderr:
                raise ValueError("视频颜色转换不可用，请检查 FFmpeg colorspace 滤镜")
            raise ValueError("视频帧解码失败，请检查原视频是否完整")
        return result

    @staticmethod
    def _cache_key(asset) -> tuple:
        return (asset.workspace_id, asset.id, asset.sha256, asset.object_key, COLOR_CONVERSION_VERSION)

    def _retain(self, key: tuple, video: CachedVideo) -> CachedVideo:
        video.used_at = time.monotonic()
        video.in_use += 1
        self._videos.move_to_end(key)
        return video

    def _release(self, video: CachedVideo | None) -> None:
        if video is None:
            return
        with self._lock:
            video.in_use = max(0, video.in_use - 1)

    def _evict_for(self, incoming_size: int) -> None:
        while self._videos:
            used = sum(item.path.stat().st_size for item in self._videos.values())
            if len(self._videos) < 2 and used + incoming_size <= 2 * 1024**3:
                return
            victim = next((key for key, item in self._videos.items() if not item.in_use), None)
            if victim is None:
                return
            self._videos.pop(victim).directory.cleanup()
            self._work_locks.pop(victim, None)

    def _load_video(self, asset) -> CachedVideo:
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
                "frame=best_effort_timestamp,best_effort_timestamp_time,key_frame:format=start_time:stream=start_time,color_space,color_transfer,color_primaries,color_range",
                "-of", "json", str(path),
            ])
            info = json.loads(result.stdout)
            frames = _probe_frames(info)
            start = float(info.get("format", {}).get("start_time") or
                          info.get("streams", [{}])[0].get("start_time") or 0)
            color_conversion = _source_color(info.get("streams", [{}])[0])
            return CachedVideo(directory, path, frames, [frame.seconds - start for frame in frames],
                               start, time.monotonic(), color_conversion)
        except Exception:
            directory.cleanup()
            raise

    def _video(self, asset) -> CachedVideo:
        key = self._cache_key(asset)
        with self._lock:
            if self._closed:
                raise ValueError("视频选帧服务已关闭")
            cached = self._videos.get(key)
            if cached:
                return self._retain(key, cached)
            event = self._inflight.get(key)
            we_prepare = event is None
            if we_prepare:
                event = threading.Event()
                self._inflight[key] = event
        if not we_prepare:
            event.wait()
            with self._lock:
                if self._closed:
                    raise ValueError("视频选帧服务已关闭")
                cached = self._videos.get(key)
                if cached:
                    return self._retain(key, cached)
            return self._video(asset)
        try:
            loaded = self._load_video(asset)
            with self._lock:
                if self._closed:
                    loaded.directory.cleanup()
                    raise ValueError("视频选帧服务已关闭")
                self._evict_for(asset.size_bytes)
                self._videos[key] = loaded
                return self._retain(key, loaded)
        finally:
            with self._lock:
                self._inflight.pop(key, None)
            event.set()

    @staticmethod
    def _index(video: CachedVideo, seconds: float, index: int | None, direction: int) -> int:
        if index is None:
            index = max(0, bisect.bisect_right(video.times, seconds + 0.000001) - 1)
        if index < 0 or index >= len(video.frames):
            raise ValueError("视频帧不存在，请重新定位")
        return max(0, min(len(video.frames) - 1, index + direction))

    def _frame_payload(self, video: CachedVideo, asset, index: int) -> dict:
        return {"frame_index": index, "time_seconds": max(0, video.times[index]),
                "total_frames": len(video.frames), "source_sha256": asset.sha256,
                "color_conversion": video.color_conversion}

    def locate(self, asset, seconds: float = 0, index: int | None = None, direction: int = 0) -> dict:
        video = self._video(asset)
        try:
            index = self._index(video, seconds, index, direction)
            return self._frame_payload(video, asset, index)
        finally:
            self._release(video)

    def extract(self, asset, seconds: float = 0, index: int | None = None) -> tuple[dict, bytes]:
        key = self._cache_key(asset)
        with self._lock:
            work = self._work_locks.setdefault(key, threading.RLock())
        with work:
            video = self._video(asset)
            try:
                index = self._index(video, seconds, index, 0)
                frame = video.frames[index]
                output = Path(video.directory.name) / f"{index}-{COLOR_CONVERSION_VERSION}.png"
                if not output.exists():
                    key_index = index
                    while key_index > 0 and not video.frames[key_index].keyframe:
                        key_index -= 1
                    seek = max(0, video.frames[key_index].seconds - video.start_seconds)
                    temporary = output.with_name(f"partial-{index}-{COLOR_CONVERSION_VERSION}.png")
                    try:
                        result = self._run([
                            self.settings.ffmpeg_path, "-v", "error", "-nostdin", "-y", "-copyts",
                            "-ss", f"{seek:.9f}", "-i", str(video.path), "-map", "0:v:0",
                            "-vf", f"select=eq(pts\\,{frame.pts}),{_color_filter(video.color_conversion)}",
                            "-fps_mode", "passthrough", "-frames:v", "1", "-c:v", "png",
                            "-f", "image2pipe", "-",
                        ])
                        if not result.stdout:
                            raise ValueError("未能解码选中的帧，请重新定位后再截图")
                        with Image.open(BytesIO(result.stdout)) as decoded:
                            decoded.convert("RGB").save(temporary, format="PNG", icc_profile=_SRGB_PROFILE)
                        temporary.replace(output)
                    finally:
                        temporary.unlink(missing_ok=True)
                payload = output.read_bytes()
                images = sorted(Path(video.directory.name).glob("*.png"), key=lambda p: p.stat().st_mtime)
                for old in images[:-8]:
                    if old != output:
                        old.unlink(missing_ok=True)
                return self._frame_payload(video, asset, index), payload
            finally:
                self._release(video)
