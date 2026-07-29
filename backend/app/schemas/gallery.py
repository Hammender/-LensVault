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
    match_score: float | None
    second_person_id: int | None = None
    second_match_score: float | None = None
    match_margin: float | None = None
    embedding_version: str | None = None
    face_size: float | None = None
    blur_score: float | None = None
    pose_yaw: float | None = None
    needs_review: bool
    vector_collection: str | None


class GalleryPhotoListItem(BaseModel):
    id: int
    filename: str
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
