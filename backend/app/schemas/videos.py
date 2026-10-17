from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime
class VideoCategoryTagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class VideoCategoryTagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class VideoCategoryTagRead(BaseModel):
    id: int
    name: str
    created_at: datetime

    model_config = {"from_attributes": True}


class VideoPersonRead(BaseModel):
    id: int
    name: str
    note: str | None
    avatar_url: str | None
    created_at: datetime
    updated_at: datetime


class VideoPersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    note: str | None = None


class VideoTagBindCreate(BaseModel):
    tag_id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "VideoTagBindCreate":
        if bool(self.tag_id) == bool(self.name and self.name.strip()):
            raise ValueError("Provide either tag_id or name.")
        if self.name is not None:
            self.name = self.name.strip()
        return self


class VideoPersonBindCreate(BaseModel):
    person_id: int


class VideoSubtitleTrackRead(BaseModel):
    id: int
    video_id: int
    language: str
    label: str
    source_language: str | None
    provider: str
    status: str
    error_message: str | None
    task_id: str | None
    generated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    vtt_url: str | None = None
    srt_url: str | None = None

    model_config = {"from_attributes": True}

class VideoSubtitleTrackUpdate(BaseModel):
    content_vtt: str


class VideoItemListItem(BaseModel):
    source_summary: dict = Field(default_factory=dict)
    id: int
    title: str
    description: str | None
    filename: str
    content_type: str | None
    size_bytes: int
    duration_seconds: float | None
    width: int | None
    height: int | None
    original_video_codec: str | None
    original_audio_codec: str | None
    video_codec: str | None
    audio_codec: str | None
    status: str
    video_type: Literal["short", "long"] = "short"
    category_tags: list[VideoCategoryTagRead]
    people: list[VideoPersonRead]
    stream_url: str
    play_url: str
    cover_url: str | None
    faststart_applied: bool
    seek_optimized: bool
    seek_optimized_at: datetime | None
    seek_keyframe_interval_seconds: float | None
    processed_at: datetime | None
    processing_error: str | None
    created_at: datetime
    updated_at: datetime
    subtitle_tracks: list[VideoSubtitleTrackRead] = Field(default_factory=list)


class VideoItemDetail(VideoItemListItem):
    sha256: str | None


class PaginatedVideos(BaseModel):
    items: list[VideoItemListItem]
    total: int
    offset: int
    limit: int


class VideoMetadataUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = None
    video_type: Literal["short", "long"] | None = None


class VideoUploadSessionCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    description: str | None = None
    filename: str = Field(min_length=1, max_length=512)
    content_type: str | None = None
    size_bytes: int = Field(gt=0)
    part_size: int | None = Field(default=None, gt=0)
    sha256: str | None = Field(default=None, min_length=64, max_length=64)


class VideoUploadSessionRead(BaseModel):
    id: str
    filename: str
    title: str
    description: str | None
    content_type: str | None
    size_bytes: int
    part_size: int
    total_parts: int
    uploaded_parts: list[int]
    status: str
    created_at: datetime
    updated_at: datetime


class VideoUploadPartRead(BaseModel):
    session_id: str
    part_index: int
    size_bytes: int
    sha256: str | None


class VideoUploadCompleteRequest(BaseModel):
    category_tag_ids: list[int] = Field(default_factory=list)
    category_tag_names: list[str] = Field(default_factory=list)
    person_ids: list[int] = Field(default_factory=list)
    generate_zh_subtitles: bool = False
    video_type: Literal["short", "long"] | None = None

    @model_validator(mode="after")
    def normalize_names(self) -> "VideoUploadCompleteRequest":
        self.category_tag_names = list(
            dict.fromkeys(name.strip() for name in self.category_tag_names if name.strip())
        )
        return self
