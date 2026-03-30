from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PersonCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    note: str | None = None


class PersonUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    note: str | None = None


class MergePersonsRequest(BaseModel):
    source_ids: list[int]
    target_id: int


class PersonRead(BaseModel):
    id: int
    name: str
    note: str | None
    photo_count: int = 0
    created_at: datetime

    model_config = {"from_attributes": True}


class PhotoTagRead(BaseModel):
    person_id: int
    person_name: str
    source: str


class FaceRead(BaseModel):
    id: int
    bbox_left: float
    bbox_top: float
    bbox_right: float
    bbox_bottom: float
    matched_person_id: int | None
    match_score: float | None
    needs_review: bool
    cluster_key: str | None


class PhotoListItem(BaseModel):
    id: int
    filename: str
    width: int | None
    height: int | None
    taken_at: datetime | None
    tags: list[PhotoTagRead]
    thumbnail_url: str
    original_url: str


class PhotoDetail(PhotoListItem):
    faces: list[FaceRead]
    object_key: str
    content_type: str | None
    created_at: datetime


class PaginatedPhotos(BaseModel):
    items: list[PhotoListItem]
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


class ClusterItem(BaseModel):
    cluster_key: str
    face_ids: list[int]
    photo_id: int
    thumbnail_url: str


class ClusterGroup(BaseModel):
    cluster_key: str
    count: int
    sample: ClusterItem


class AssignClusterRequest(BaseModel):
    person_name: str
    note: str | None = None


class AddPhotoTagRequest(BaseModel):
    person_id: int
