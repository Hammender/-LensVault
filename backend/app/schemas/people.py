from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.schemas.base import BaseModel, ShanghaiDateTime as datetime
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
    quality_status: str | None = None
    quality_warnings: str | None = None
    source_type: str = "upload"
    source_gallery_photo_id: int | None = None
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
