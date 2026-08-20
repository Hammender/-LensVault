from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime
class GalleryPersonTagRead(BaseModel):
    person_id: int
    person_name: str
    is_unknown: bool
    source: str
    promoted_sample_id: int | None = None


class GalleryTagRead(BaseModel):
    id: int
    name: str
    is_system: bool


class FaceRead(BaseModel):
    id: int
    bbox_left: float
    bbox_top: float
    bbox_right: float
    bbox_bottom: float
    matched_person_id: int | None
    predicted_person_id: int | None = None
    predicted_person_name: str | None = None
    match_score: float | None
    predicted_match_source: Literal["sample", "centroid"] | None = None
    predicted_sample_photo_id: int | None = None
    second_person_id: int | None = None
    second_person_name: str | None = None
    second_match_score: float | None = None
    second_match_source: Literal["sample", "centroid"] | None = None
    second_sample_photo_id: int | None = None
    match_margin: float | None = None
    rejection_reason: str | None = None
    recognition_adapter_id: str | None = None
    decision_threshold: float | None = None
    decision_min_margin: float | None = None
    embedding_version: str | None = None
    face_size: float | None = None
    blur_score: float | None = None
    pose_yaw: float | None = None
    needs_review: bool
    vector_collection: str | None


class GalleryPhotoListItem(BaseModel):
    id: int
    filename: str
    size_bytes: int | None
    width: int | None
    height: int | None
    taken_at: datetime | None
    is_rich_text: bool
    rich_text: str | None
    ocr_status: str | None
    persons: list[GalleryPersonTagRead]
    tags: list[GalleryTagRead]
    thumbnail_url: str
    animated_thumbnail_url: str
    original_url: str


class GalleryPhotoDetail(GalleryPhotoListItem):
    faces: list[FaceRead]
    created_at: datetime
    content_type: str | None
    recognition_summary: dict[str, int] | None = None


class PaginatedGalleryPhotos(BaseModel):
    items: list[GalleryPhotoListItem]
    total: int
    offset: int
    limit: int


class TaskRead(BaseModel):
    id: str
    kind: str
    status: str
    message: str | None
    progress: float
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GalleryPhotoPersonTagCreate(BaseModel):
    person_id: int


class GalleryPhotoTagCreate(BaseModel):
    tag_id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "GalleryPhotoTagCreate":
        if bool(self.tag_id) == bool(self.name and self.name.strip()):
            raise ValueError("Provide either tag_id or name.")
        if self.name is not None:
            self.name = self.name.strip()
        return self


class GalleryPhotoRichTextUpdate(BaseModel):
    rich_text: str | None = None


class GalleryPhotoBatchDeleteRequest(BaseModel):
    photo_ids: list[int] = Field(min_length=1)


class GalleryPhotoExportRequest(BaseModel):
    scope: Literal["all", "filtered", "selected", "from_start"]
    photo_ids: list[int] = Field(default_factory=list)
    start_photo_id: int | None = None
    person_ids: list[int] = Field(default_factory=list)
    tag_ids: list[int] = Field(default_factory=list)
    exclude_person_ids: list[int] = Field(default_factory=list)
    exclude_tag_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_scope(self) -> "GalleryPhotoExportRequest":
        if self.scope == "selected" and not self.photo_ids:
            raise ValueError("请至少选择一张图片。")
        if self.scope == "from_start" and self.start_photo_id is None:
            raise ValueError("请选择范围起点图片。")
        return self


class TagStatistics(BaseModel):
    tag_id: int
    tag_name: str
    is_system: bool
    photo_count: int


class UploadHistoryRead(BaseModel):
    id: int
    upload_type: str
    total_count: int
    success_count: int
    duplicate_count: int
    created_at: datetime

    model_config = {"from_attributes": True}


class StatisticsOverview(BaseModel):
    gallery_total: int
    gallery_photo_count: int
    rich_photo_count: int
    source_counts: dict[str, int]
    person_covered_count: int
    tag_covered_count: int
    acquisition_status_counts: dict[str, int]


class ImageIntakeActivity(BaseModel):
    id: str
    source: str
    status: str
    total_count: int
    imported_count: int
    updated_count: int
    skipped_count: int
    failed_count: int
    completed_at: datetime


class PaginatedImageIntakeActivities(BaseModel):
    items: list[ImageIntakeActivity]
    total: int
    offset: int
    limit: int


class PersonStatistics(BaseModel):
    person_id: int
    person_name: str
    display_name: str
    is_unknown: bool
    photo_count: int
    sample_count: int


class ExportSamplePhoto(BaseModel):
    filename: str
    sha256: str
    content_type: str | None = None
    object_key: str
    width: int | None = None
    height: int | None = None
    taken_at: datetime | None = None


class ExportPerson(BaseModel):
    name: str
    display_name: str
    note: str | None = None
    is_unknown: bool
    tags: list[str]
    samples: list[ExportSamplePhoto]


class ExportManifest(BaseModel):
    version: int
    exported_at: datetime
    persons: list[ExportPerson]


class ImportResult(BaseModel):
    created_persons: int = 0
    existing_persons: int = 0
    added_samples: int = 0
    skipped_samples: int = 0
    tags_added: int = 0
