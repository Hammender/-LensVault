from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    note: str | None = None


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    note: str | None = None


class PersonRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=256)


class PersonBatchDeleteRequest(BaseModel):
    person_ids: list[int] = Field(min_length=1)


class PersonRead(BaseModel):
    id: int
    name: str
    display_name: str
    note: str | None
    is_unknown: bool
    unknown_serial: int | None
    sample_count: int = 0
    gallery_photo_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class SamplePhotoRead(BaseModel):
    id: int
    filename: str
    width: int | None
    height: int | None
    taken_at: datetime | None
    status: str
    error_message: str | None
    thumbnail_url: str
    original_url: str
    created_at: datetime


class TagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class TagUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)


class TagRead(BaseModel):
    id: int
    name: str
    is_system: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class PersonTagCreate(BaseModel):
    tag_id: int | None = None
    name: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "PersonTagCreate":
        if bool(self.tag_id) == bool(self.name and self.name.strip()):
            raise ValueError("Provide either tag_id or name.")
        if self.name is not None:
            self.name = self.name.strip()
        return self


class GalleryPersonTagRead(BaseModel):
    person_id: int
    person_name: str
    is_unknown: bool
    source: str


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
    original_url: str


class GalleryPhotoDetail(GalleryPhotoListItem):
    faces: list[FaceRead]
    created_at: datetime
    content_type: str | None


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
