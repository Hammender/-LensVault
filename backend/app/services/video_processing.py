from __future__ import annotations


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
