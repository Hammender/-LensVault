from __future__ import annotations

import logging
import subprocess
import tempfile
import time
from pathlib import Path


logger = logging.getLogger(__name__)


def extract_video_cover_frame(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    *,
    capture_at: float = 1.0,
    duration_seconds: float | None = None,
    timeout: int = 120,
) -> bool:
    """Decode a single frame for a review/list poster. Does not transcode the video."""
    seek_at = capture_at
    if duration_seconds and duration_seconds > 0:
        seek_at = min(max(capture_at, duration_seconds * 0.1), max(duration_seconds - 0.1, 0))
    command = [
        ffmpeg_path,
        "-y",
        "-ss",
        f"{seek_at:.3f}",
        "-i",
        str(input_path),
        "-frames:v",
        "1",
        "-vf",
        "scale=1280:-2:force_original_aspect_ratio=decrease",
        "-q:v",
        "3",
        str(output_path),
    ]
    started_at = time.monotonic()

    def run(args: list[str]) -> subprocess.CompletedProcess:
        remaining = timeout - (time.monotonic() - started_at)
        if remaining <= 0:
            raise subprocess.TimeoutExpired(args, timeout)
        return subprocess.run(args, capture_output=True, text=True, timeout=remaining, check=False)

    result = run(command)
    if result.returncode != 0 and "Invalid color space" in (result.stderr or ""):
        # 无效矩阵标记会在滤镜入口就失败，setparams 无法补救。只修复临时片段的标记。
        codec = next((name for name in ("h264", "hevc") if f"{name} (native)" in result.stderr), None)
        if codec:
            with tempfile.TemporaryDirectory(prefix="video-cover-color-") as directory:
                sample = Path(directory) / "sample.mp4"
                repaired = run([
                    ffmpeg_path, "-y", "-ss", f"{seek_at:.3f}", "-i", str(input_path),
                    "-map", "0:v:0", "-t", "1", "-c:v", "copy",
                    "-bsf:v", f"{codec}_metadata=matrix_coefficients=1", "-an", str(sample),
                ])
                if repaired.returncode == 0:
                    retry = list(command)
                    retry[retry.index("-ss") + 1] = "0"
                    retry[retry.index("-i") + 1] = str(sample)
                    result = run(retry)
    if result.returncode != 0:
        logger.warning("Video cover extraction failed: %s", (result.stderr or result.stdout or "").strip()[-1000:])
        return False
    return output_path.is_file() and output_path.stat().st_size > 0


class VideoProbeInfo:
    def __init__(
        self,
        duration_seconds: float | None,
        width: int | None,
        height: int | None,
        video_codec: str | None,
        audio_codec: str | None,
        fps: float | None = None,
        pixel_format: str | None = None,
    ) -> None:
        self.duration_seconds = duration_seconds
        self.width = width
        self.height = height
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        self.fps = fps
        self.pixel_format = pixel_format


class VideoTranscodePlan:
    def __init__(
        self,
        encoder: str,
        target_codec: str,
        device_label: str,
        is_hardware: bool,
        encoder_args: list[str],
    ) -> None:
        self.encoder = encoder
        self.target_codec = target_codec
        self.device_label = device_label
        self.is_hardware = is_hardware
        self.encoder_args = encoder_args
