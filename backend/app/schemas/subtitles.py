from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator
from .gallery import TaskRead
from .videos import VideoSubtitleTrackRead

class SubtitleAsrStatus(BaseModel):
    status: str
    loaded: bool
    model_path: str
    device: str
    compute_type: str
    current_video_id: int | None
    current_task_id: str | None
    message: str | None
    last_duration_seconds: float | None
    last_language: str | None
    last_segment_count: int | None
    last_error: str | None


class SubtitleServiceStatus(BaseModel):
    status: str
    healthy: bool
    managed: bool
    pid: int | None
    endpoint: str
    model: str
    model_path: str
    server_path: str | None
    log_path: str | None
    message: str | None
    asr: SubtitleAsrStatus


class SubtitleServiceLogs(BaseModel):
    log_path: str | None
    exists: bool
    content: str


class SubtitleJobRead(BaseModel):
    video_id: int
    video_title: str
    video_filename: str
    track: VideoSubtitleTrackRead
    task: TaskRead | None
